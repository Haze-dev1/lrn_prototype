# LRN

Adaptive technical interview preparation for students recruiting into investment banking and
private equity.

Students answer real technical questions in free text. Those answers are graded against
structured rubrics, producing evidence — concepts demonstrated, concepts missed, known mistakes,
and coaching — which drives a per-category mastery score and adaptive practice selection.

**Answer → Evaluate → Understand → Practise → Improve**

The product specification is [`LRN_Detailed_PRD_v1.md`](LRN_Detailed_PRD_v1.md). Architecture and
working conventions for contributors are in [`CLAUDE.md`](CLAUDE.md).

---

## Current state

Phases 1-11 are complete. The containerised topology runs, accounts work end to end, the question
bank holds forty authored questions with an admin surface, AI grading runs through a replaceable
provider abstraction with a full audit trail, the 24-question diagnostic works end to end,
adaptive practice selects by weakness, spaced repetition, novelty and difficulty fit, review and
progress close the loop, and **billing is server-authoritative** — Stripe hosted Checkout and
Customer Portal, signature-verified webhooks that are idempotent at the database, an entitlement
lifecycle that survives out-of-order and undelivered events, and free-tier limits enforced in the
API rather than in the interface, and **transactional email and product analytics are wired
end to end** — diagnostic results and payment confirmations, a weekly weak-area nudge with
one-click unsubscribe, and a funnel whose events carry identifiers and numbers but never a word a
student wrote.

A full UX quality pass has been done — a marketing landing page that demonstrates the grading
rather than describing it, route-level loading, error and not-found states, a nav that works on a
phone, and a way out of a running session.

The security gate and the performance pass follow. See
[`checkpoints/`](checkpoints/) for what is verified at each step, and
[`docs/implementation-assessment.md`](docs/implementation-assessment.md) for the target
architecture and known risks.

---

## Stack

| Layer | Technology |
|---|---|
| Web | Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS v4 |
| API | Python 3.13, FastAPI, SQLAlchemy 2 (async), Alembic |
| Database | PostgreSQL 18 (Docker, named volume) |
| Cache / coordination | Redis 8 (Docker) |
| Scheduled work | APScheduler in a dedicated container, Redis-backed locking |
| Reverse proxy | Caddy — same-origin routing, TLS in production |
| AI grading | OpenRouter behind an internal provider abstraction |

---

## Requirements

- Docker Engine and the Compose v2 plugin
- Your user must be in the `docker` group (`sudo usermod -aG docker $USER`, then log out and in)
- For running tests outside containers: [uv](https://docs.astral.sh/uv/) and Node.js 24+

---

## Quick start

```bash
cp .env.example .env      # then set JWT_SECRET and POSTGRES_PASSWORD
make up                   # build and start every service
make migrate              # apply database migrations
make seed                 # load the authored question bank
```

The application is served at **http://localhost:8080**.

Generate a JWT secret with:

```bash
openssl rand -hex 32
```

`make help` lists every available command.

---

## Service topology

One origin fronts both applications, which is what allows the session cookie to be `HttpOnly` and
`SameSite=Lax` with no CORS surface and no token in browser-accessible storage.

```
Browser
   │
   ▼
proxy (Caddy, :8080)
   ├── /api/*  ──▶  api (FastAPI, :8000)
   └── /*      ──▶  web (Next.js, :3000)

api, scheduler  ──▶  postgres (:5432)   durable source of truth
                └─▶  redis (:6379)      locks, rate limits, cache
```

Development and production run the same six services. `docker-compose.yml` is production-shaped;
`docker-compose.override.yml` — which Compose loads automatically — adds source mounts, hot
reload, and loopback datastore ports for development only.

Compose **merges** list fields such as `volumes` and `ports`, so an override file cannot remove
an entry a base file declared. The base file therefore contains nothing production must strip,
and the override only ever adds. Production runs `docker compose -f docker-compose.yml` to
exclude the override entirely.

| Service | Purpose | Health check |
|---|---|---|
| `proxy` | TLS termination, same-origin routing | — |
| `web` | Next.js application | `GET /health` |
| `api` | FastAPI application | `GET /health` |
| `scheduler` | APScheduler process | Redis heartbeat key |
| `postgres` | Durable application data | `pg_isready` |
| `redis` | Ephemeral state and coordination | `redis-cli ping` |

In development, `postgres` and `redis` publish to `127.0.0.1` only, so local tooling can reach
them but the network cannot. In production neither publishes a port.

---

## Environment variables

Every variable is documented in [`.env.example`](.env.example). `.env` is git-ignored and must
never be committed. The ones you must set before the stack is usable:

| Variable | Purpose |
|---|---|
| `POSTGRES_PASSWORD` | Database password; must match the credentials in `DATABASE_URL` |
| `DATABASE_URL` | Application connection string; the host is the Compose service name, not `localhost` |
| `REDIS_URL` | Redis connection string |
| `JWT_SECRET` | Session token signing key, minimum 32 characters |
| `GRADING_PROVIDER` | `fake` for local development and tests, `openrouter` once a key is set |
| `SITE_ADDRESS` | `:80` for plain HTTP locally, or a hostname to enable automatic TLS |
| `GOOGLE_CLIENT_ID` | Optional. Enables Google sign-in; no client secret is needed or stored |
| `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` | Optional. Without them checkout answers 503 and the webhook refuses every request |
| `STRIPE_PRICE_PRO_MONTHLY` / `STRIPE_PRICE_SEASON_PASS` | Price IDs; a plan with no price is shown as unavailable rather than offered |
| `FREE_PRACTICE_SESSIONS` / `FREE_DAILY_GRADED_ATTEMPTS` | Free-tier limits, enforced server-side |
| `EMAIL_PROVIDER` | `log` writes messages to the log and sends nothing; `resend` sends for real |
| `ANALYTICS_PROVIDER` | `log` records locally, `posthog` sends, `none` switches analytics off |
| `PROXY_HTTP_PORT` / `PROXY_HTTPS_PORT` | Host ports the proxy publishes (`8080`/`8443` locally) |
| `HOST_UID` / `HOST_GID` | Your `id -u` / `id -g`, so files written into bind mounts are yours |

`OPENROUTER_API_KEY`, `GOOGLE_CLIENT_ID`, `RESEND_API_KEY`, `POSTHOG_API_KEY` and `SENTRY_DSN`
are optional; the stack runs without them, with the corresponding feature reporting itself as
unconfigured rather than failing.

### Local email and analytics

Both default to a local provider that writes to the application log and makes no network call, so
a fresh clone exercises the whole path without an account anywhere. To read a rendered message
during development, set `LOG_LEVEL=DEBUG` — the log provider writes the full text body at that
level and the subject and recipient at `INFO`.

### Local payments

There is deliberately no fake payment provider. A fake grade is obviously local; fake paid access
would be indistinguishable from access that was bought, and entitlements must come only from
verified payment events. Use Stripe test-mode keys, which are free:

```bash
stripe listen --forward-to localhost:8080/api/v1/webhooks/stripe
```

The command prints a signing secret — put it in `STRIPE_WEBHOOK_SECRET`. Without one the webhook
endpoint refuses every request, which is correct: an unverified event is not a payment event.

---

## Database migrations

Migrations are version-controlled with Alembic and are the only supported way to change the
schema. Never edit a deployed schema by hand.

```bash
make migrate                              # apply all pending migrations
make migration m="add attempts table"     # autogenerate a new revision
make downgrade                            # revert the most recent revision
make psql                                 # open a psql shell
```

A new model is invisible to autogenerate until it is imported in `backend/core/models/__init__.py`.

The schema requires **PostgreSQL 18 or newer** for its native `uuidv7()` primary keys.

---

## Question bank content

The question bank is authored in `backend/seeds/questions.json` and loaded by a seeder that is
safe to re-run:

```bash
make seed          # create or update questions from the content file
make seed-check    # validate the content without writing anything
```

Each entry carries a `source_key`, which is how the seeder matches an entry to a question it has
already created. Re-running with unchanged content writes nothing; editing a prompt or rubric
publishes a new version and supersedes the previous one, so history is never overwritten. Editing
only a category or difficulty updates the question without creating a version.

Every entry is validated for rubric completeness before anything is written, and a single invalid
entry aborts the whole run. `backend/tests/test_question_seed.py` runs the same validation against
the committed content, so an incomplete question fails CI rather than a deployment.

Content can also be authored through the admin interface at `/admin/questions`, which requires an
account with `is_admin` set. There is no self-service route to become an administrator; the column
is set directly in the database.

---

## AI grading

Grading runs entirely server-side. The API key is read from the environment and never reaches the
browser.

```bash
GRADING_PROVIDER=fake         # deterministic, no network call, no key needed (default)
GRADING_PROVIDER=openrouter   # real grading; requires OPENROUTER_API_KEY
```

The default is `fake`, so a fresh clone has working grading with no account anywhere. It grades by
term overlap: not intelligent, but deterministic and discriminating, which is what makes it useful
for development and tests.

An answer is persisted before grading is attempted, graded by a background task, and polled by the
client at `GET /v1/attempts/{id}`. A grading failure preserves the answer and never writes a score;
a scheduled sweep finishes anything left unresolved by a crash or a deploy.

The diagnostic is the first place a student meets grading: 24 questions, three from each
category, composed by the server and stored so a refresh resumes the same sitting. It does not
reveal a grade per question — it is an assessment, and all 24 scores land together on the results
page.

## Practice

Practice sets are 5, 10 or 20 questions, chosen from the student's weakest categories, anything
they previously missed that has come due for review, and material they have not seen. Selection is
a weighted sum of four named signals — no ML — and every session stores the sentence explaining
which of them drove it, so *"Valuation is your weakest category, and 2 previous misses are due for
review"* is a description of what actually happened rather than copy.

Unlike the diagnostic, practice reveals the grade after each answer: score, band, the concepts
shown and missed, mistakes, coaching, and the reference answer.

---

## Review and progress

Every graded answer is reviewable, filtered by category, score, a specific concept missed, recency
or whether the student disputed the grade. A student can flag a grade they think is wrong; flags
are a quality signal on the question bank as much as a support channel.

Progress shows per-category mastery and a weekly trend. Mastery is only ever shown where there is
graded evidence behind it — a category with none reads "Not measured yet", never zero.

---

To check grading quality before changing the model, the prompt, or a rubric:

```bash
make benchmark     # or: uv run python -m scripts.run_grading_benchmark
```

This runs a set of human-labelled answers through the real grading path and reports how often the
grader agreed with the human, broken down by the kind of answer. Against `openrouter` it makes one
real model call per case.

---

## Running without Docker

Docker is the supported path. To run a service directly — for a debugger, say — start the
datastores first with `docker compose up -d postgres redis`, then point `DATABASE_URL` and
`REDIS_URL` at `localhost`.

```bash
# API
cd backend && uv sync --group dev && uv run python main.py

# Web
cd web && npm install && npm run dev
```

---

## Tests and quality gates

```bash
make check        # lint + typecheck + tests, backend and frontend
make test         # tests only
make lint
make typecheck
```

Individually:

```bash
cd backend && uv run pytest -q
cd web && npm test && npm run typecheck && npm run lint
```

Backend tests that need PostgreSQL or Redis skip cleanly when the stack is down, so `make test-api`
works either way — it reports 55 skipped rather than failing. `make test-api` derives the test
database URL from `.env` and uses a separate `<POSTGRES_DB>_test` database, created and migrated
automatically on first run. No test uses a live third-party credential.

---

## Production deployment

Target is a single AWS EC2 host running the same Compose topology.

Set these in the production `.env`:

```ini
SITE_ADDRESS=lrn.example.com     # a hostname makes Caddy provision and renew TLS automatically
TLS_CONTACT_EMAIL=ops@example.com
PROXY_HTTP_PORT=80
PROXY_HTTPS_PORT=443
ENVIRONMENT=production
```

Then:

```bash
make prod-up          # docker compose -f docker-compose.yml up -d --build
```

`make prod-up` deliberately omits `docker-compose.override.yml`, so no source is bind-mounted and
neither datastore publishes a host port. In `production`, the API also stops serving `/docs` and
`/openapi.json`.

Database data lives in the `postgres_data` named volume and survives container recreation and
image replacement — this is verified, not assumed. The volume is not a backup: EC2 needs a
snapshot or `pg_dump` schedule of its own.

The topology is designed so PostgreSQL can move to RDS and Redis to ElastiCache by changing
`DATABASE_URL` and `REDIS_URL`, with no application changes.

---

## Repository layout

```
backend/     FastAPI application — routes, controllers, CRUD, services, models, jobs
web/         Next.js application — app routes, features, components, API client
infra/       Caddy reverse proxy configuration (one file, both environments)
docs/        Architecture assessment and decision records
checkpoints/ Per-phase completion records with verification evidence
```
