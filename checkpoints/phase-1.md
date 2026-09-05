# Checkpoint — Phase 1: Foundation

**Completed:** 2026-09-03
**Goal:** make the project runnable with the target architecture. No product features.

---

## What was built

| Area | Delivered |
|---|---|
| Topology | 6 services (`proxy` `web` `api` `scheduler` `postgres` `redis`) in Docker Compose |
| Backend | FastAPI app, Eigi layering (route → controller → CRUD/service), settings, async SQLAlchemy engine + session, Redis client, structured logger |
| Scheduler | APScheduler in its own container, Redis-backed distributed lock, observable heartbeat |
| Migrations | Alembic wired to application settings and `Base.metadata` |
| Frontend | Next.js 16 App Router, design tokens, `Button`/`Badge` primitives, typed API client |
| Proxy | Caddy, same-origin routing (`/api/*` → api, `/*` → web), security headers, TLS in production |
| Quality | ruff, mypy, pytest, eslint, tsc, vitest, GitHub Actions CI |
| Docs | `README.md`, `CLAUDE.md`, `.env.example` |

---

## Verification — commands run and their actual output

### Services
```
SERVICE     STATUS
api         Up 25 seconds (healthy)
postgres    Up 31 seconds (healthy)
proxy       Up 19 seconds
redis       Up 31 seconds (healthy)
scheduler   Up 25 seconds (healthy)
web         Up 19 seconds (healthy)
```
Verified from a clean `docker compose down -v` followed by `make up`.

### End-to-end HTTP through the proxy
```
/api/health         200 {"status":"alive"}
/api/health/ready   200 {"status":"healthy","service":"LRN API",
                         "dependencies":[{"name":"postgres","healthy":true},
                                         {"name":"redis","healthy":true}]}
/health (web)       200 {"status":"alive"}
/ (landing)         200  — server-rendered page shows both dependencies "connected"
```
The landing page is server-rendered by the `web` container calling `api` over the Docker
network, so this proves the whole chain: browser → Caddy → Next.js SSR → FastAPI → Postgres+Redis.

### Health checks detect real failure (not hardcoded)
```
redis stopped  -> /api/health/ready 503  {"status":"degraded", redis healthy:false}
               -> /api/health       200  (liveness does no I/O, correctly unaffected)
redis started  -> /api/health/ready 200
```

### Migrations
```
alembic upgrade head              -> OK
tables in public schema           -> alembic_version
alembic revision --autogenerate   -> Generating .../e824ab77204e_autogenerate_probe.py ... done
                                     -rw-r--r-- 1 haze haze  (owned by the developer, not root)
```
The autogenerate probe was deleted afterwards; no revisions are committed, which is correct
while no models exist. The chain settings → `Base.metadata` → Alembic is proven working before
Phase 2 depends on it.

### Distributed job locking
8 concurrent workers contending for one job name:
```
results.count(True) == 1   results.count(False) == 7
```
Covered by four integration tests in `backend/tests/test_job_locks.py` against real Redis,
including release-on-exception and the compare-and-delete guard that stops an overrunning worker
deleting a lock another worker now holds.

### Scheduler liveness
```
lrn:scheduler:heartbeat = 2026-09-03T16:43:21.719267+00:00  (ttl 50)
python -m core.jobs.healthcheck  -> exit 0
```

### Data persistence across container recreation
```
insert 'kept' -> docker compose rm -sf postgres -> up -d postgres
value after recreate: kept
```

### Quality gates
```
backend  ruff check          All checks passed!
backend  ruff format --check 38 files already formatted
backend  mypy core commons   Success: no issues found in 31 source files
backend  pytest              8 passed            (with Redis)
backend  pytest              4 passed, 4 skipped (without Redis — skip guard works)
web      eslint              clean
web      tsc --noEmit        clean
web      vitest              2 files, 9 tests passed
web      next build          Compiled successfully
```

---

## Problems found and fixed during verification

These were caught by running things, not by reading them. Each would have shipped silently.

1. **Postgres 18 refused to start.** The image expects its mount at `/var/lib/postgresql`, not
   `/var/lib/postgresql/data`; the older path makes it exit with a data-directory error.

2. **The production Compose config was wrong in a security-relevant way.** `docker-compose.prod.yml`
   used `volumes: []` and `ports: []` to strip development settings, but **Compose merges list
   fields — an override cannot remove an entry a base file declared**. Rendering the production
   config showed it would have bind-mounted host source into the `web` and `api` containers and
   **published PostgreSQL and Redis to the host**. Restructured to the additive pattern: the base
   file is production-shaped, and `docker-compose.override.yml` (auto-loaded in development only)
   adds source mounts and loopback ports. Verified by rendering both configs.

3. **`alembic revision --autogenerate` failed with `PermissionError`.** The container ran as uid
   1001 while the bind-mounted source is owned by uid 1000. Development containers now run as
   `${HOST_UID}:${HOST_GID}`. Would have blocked the first task of Phase 2.

4. **Caddy crash-looped** because `email {$TLS_CONTACT_EMAIL}` with an unset variable is a
   Caddyfile parse error. Given an env default.

5. **Backend tests failed with `Event loop is closed`.** The Redis and database clients are
   process-wide singletons, but pytest-asyncio creates a loop per test. Set
   `asyncio_default_test_loop_scope = "session"`, which matches how the application actually runs.

6. **ESLint 10 broke `eslint-config-next`** (its bundled `eslint-plugin-react` calls
   `context.getFilename()`, removed in ESLint 10). Pinned to the 9.x line. Separately,
   `eslint-config-next` 16 exports native flat config arrays, so `FlatCompat` was the wrong bridge
   and threw a circular-structure error.

7. **File logging inside containers.** Removed: containers now log to stdout only, where the
   runtime handles collection and rotation. `LOG_DIR` makes file logging opt-in for non-container
   use. This also removed two named volumes and the permission conflict they created.

---

## Decisions made

| Decision | Reason |
|---|---|
| Caddy proxy in dev and prod | Same-origin routing lets the session cookie be `HttpOnly`+`SameSite=Lax` with no CORS surface and no browser-accessible token. Dev matches prod. |
| Self-contained auth in the API | User's decision. No hosted dependency; the stack runs offline. |
| `GRADING_PROVIDER=fake` default | No OpenRouter key available. Tests and local development make no network calls; the real provider is a config switch. |
| Bone-white primary action, colour reserved for mastery bands | Colour carries meaning in this product. Spending it on chrome would make a weak category compete with a button. |
| Inter + JetBrains Mono | Mono carries scores, categories and counters — tabular numerals and an assessment register; Inter carries dense prose. |
| ESLint pinned to 9.x | 10.x is incompatible with `eslint-config-next` 16 (see above). |
| TypeScript 5.9.3, not 7.0.2 | TS 7 is the native rewrite; the Next 16 + typescript-eslint toolchain is not verified against it. Not worth the risk for zero product benefit. |
| No React Query / component library | Nothing needs them yet. Server Components fetch server-side; primitives are hand-built so the UI does not read as a template. |

---

## Honest scope statement

Deliberately **not** built in this phase, and not claimed:

- No domain models, no product tables — `alembic_version` is the only table. That is Phase 2.
- No authentication, no user accounts. Phase 3.
- No questions, grading, diagnostic, practice, review, progress, or billing.
- `maintenance_job` logs and returns; it exists to exercise the locking pattern real jobs will use.
- The design system is two primitives and a token set, not the full component family in PRD §56.
- The root page is a foundation page proving service connectivity, not the marketing landing page.
- No E2E suite yet (Playwright is unconfigured); there are no user flows to test.
- `make format` covers the backend only; no Prettier was added for the web app.

---

## Blockers

None. The Docker group blocker from Phase 0 is resolved.

One environment note: this agent session's shell holds stale supplementary groups from before
`usermod -aG docker`, so Docker commands here are run through `newgrp docker`. A normal user
shell is unaffected.

---

## Next

**Phase 2 — Database and domain foundation.** Models, migrations, indexes and constraints for
`profiles`, `questions`, `question_versions`, `sessions`, `attempts`, `grade_events`,
`skill_scores`, `subscriptions`, `entitlements`, `grade_flags`; the CRUD layer; initial domain
services; CRUD tests against a real database.
