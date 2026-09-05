# Security review — launch gate

**Date:** 2026-09-05 (Phase 12 gate, extended by the Phase 14 final verification)
**Scope:** the whole application before launch — authentication, authorisation, question and
rubric protection, entitlement enforcement, webhook verification, prompt injection, secrets,
rate limiting, CORS, input validation, logging, PII, data export and deletion, admin access and
container exposure.
**Method:** deterministic scanners first, then data-flow reasoning, then live attack probes
against the running stack. Every claim below was reproduced against a real deployment or read
out of the code; none is inferred from the documentation.

---

## Verdict

**PROCEED WITH NOTES.**

Five issues were found across two passes — three at the Phase 12 gate, two more when Phase 14
drove the product end to end — and all five are fixed. None was a remote-unauthenticated
compromise, and **no cross-account access path was found anywhere in the API**.

The most serious was an assessment-integrity break: a student could read their own diagnostic
grades and reference answers mid-sitting, through two endpoints, because the rule was enforced in
the interface rather than on the server. The two found later are spending controls that did not
hold — the daily grading allowance counted the wrong event and could be walked past by concurrent
submission.

A pattern worth naming: every one of the last three findings was a control that existed, looked
correct in isolation, and did not bind. Reading the code found none of them; driving the product
found all three.

The open items at the bottom are hardening and operability, not exploitable defects.

---

## Scanners

| Tool | Status | Result |
|---|---|---|
| `bandit` (Python, 15,728 LOC) | ran | 0 high, 1 medium, 5 low — all reviewed, all false positives |
| `npm audit` (web) | ran | 0 vulnerabilities across all severities |
| `mypy` | ran | clean, 118 source files |
| `ruff` | ran | clean |
| `gitleaks` | **absent** | not installed; secret hygiene checked by hand instead |
| `trufflehog` | **absent** | not installed |
| `semgrep` | **absent** | not installed |
| `osv-scanner` | **absent** | not installed |
| `pip-audit` | **absent** | not installed |

Four secret- and pattern-scanners were unavailable. Their absence is not a clean bill of health:
Python dependency advisories in particular were **not** checked by any tool. `npm audit` covers
the frontend only.

Bandit's findings, each checked individually: `B104` binding to `0.0.0.0` in `main.py:22` is
correct for a container that is only reachable through the proxy; `B105` twice on the strings
`season_pass` and `access` is matching enum *values*, not credentials; `B101` on two `assert`
statements in `auth_controller.py` — both are mypy type-narrowing after a real check, carry a
justifying `noqa`, and stripping them under `python -O` removes no security control.

---

## Findings

### [1] HIGH — Diagnostic grades and reference answers readable mid-sitting

**Confidence:** high — reproduced live, twice, through two different endpoints.

**Location:** `backend/core/controllers/attempt_controller.py:190` (`AttemptController.get`) and
`backend/core/cruds/attempt_crud.py:109` (`list_for_user`, reached from
`review_controller.py:98`).

**Path:** authenticated student → `GET /v1/attempts/{id}` → full grade payload including
`score`, `band`, `feedback`, `concepts_missed` and `ideal_answer`, while the parent diagnostic is
still `in_progress`. The same scores reappear as a list via `GET /v1/review`.

**Evidence:** the diagnostic composition response hands the client an `attempt_id` for every
answered question, so no ID guessing is needed. Reproduced with one answer submitted out of 24:

```
GET /v1/attempts/{id}   -> score 0, band needs_work, ideal_answer "Net income from the
                           bottom of the income statement is the starting line of..."
GET /v1/review          -> 3 items, each with score and band, mid-sitting
```

**Impact:** the product's central claim is that the diagnostic is evidence of readiness. Both
`GET /v1/sessions/{id}/results` (409) and the interface already refuse to reveal anything
mid-sitting, and `CLAUDE.md` states the rule as an invariant — but `AttemptController.get`
checked only ownership, and the review list only filtered on grading status. A student polling
between questions learns their running score and reads the reference answer for material still
being assessed. That corrupts the diagnostic and every mastery score, weekly trend and practice
recommendation derived from it. It is also a rubric-adjacent disclosure during a live assessment,
which the PRD names explicitly ("no answer/rubric leakage").

This is invariant 1 inverted: the client hid a control the API did not enforce. Only the
*practice* runner polls `fetchAttempt`; the diagnostic runner never asks, which is why this was
invisible in the interface.

**Fix:** both doors closed, scoped to the diagnostic so practice is unaffected (practice reveals
grades immediately by design).

- `AttemptController.get` now loads the parent session and returns state only when it is a
  diagnostic still in progress. Placed *after* the ungraded early return, so polling an answer
  that is still grading costs no extra query.
- `CRUDAttempt.list_for_user` gained `exclude_unfinished_diagnostic`, set by the review
  controller. It is a parameter rather than an unconditional filter because the same query backs
  the **data export**, which must return everything the account holds.

**Regression tests:** `TestDiagnosticGradeWithholding` in `tests/test_attempts.py` and three
tests in `TestReviewPrivacy` in `tests/test_review.py`. Each was confirmed to fail with the fix
reverted and pass with it applied.

---

### [2] MEDIUM — A deployed environment could boot on a credential published in this repository

**Confidence:** high — reproduced by construction.

**Location:** `backend/core/config/settings.py:41`, `.env.example:17,49`.

**Path:** operator copies `.env.example` to `.env` (the documented setup step) → deploys without
editing `JWT_SECRET` → every access token is signed with
`replace-with-a-32-byte-random-value-generated-per-environment`, a value in this repository.

**Evidence:** `JWT_SECRET: str = Field(min_length=32)` proves a value was *supplied*, not that it
was *chosen*, and the published placeholder is 60 characters, so it passes. The settings docstring
claimed "secrets have no default so a misconfigured deployment fails loudly instead of running
with a placeholder credential" — true for an absent value, not for a copied one.
`POSTGRES_PASSWORD=change-me-in-every-environment` has the same shape.

**Impact:** anyone who has read the repository can forge an access token for any `sub` and
authenticate as any user, including an administrator. Complete authentication bypass for a
deployment that made one very ordinary omission.

**Fix:** a `model_validator` refuses to construct settings in `production` or `staging` when
`JWT_SECRET` or `DATABASE_URL` still contains a published placeholder marker. Development and
test are exempt — a fixed local secret is convenient and worthless to an attacker with no
deployment to attack. Refusing to boot is the only failure mode an operator cannot skip past; a
warning in a log would ship.

Verified: `production` + placeholder → refuses; `staging` + placeholder → refuses; `production` +
placeholder DB password → refuses; `production` + real secret → boots; `development` +
placeholder → boots.

**Regression tests:** `tests/test_settings_guard.py`, confirmed to fail with the guard neutered.

**Note on rotation:** no real secret was ever committed — `.env` is gitignored and untracked, and
the repository has no commits yet — so there is nothing to rotate. Had one been committed,
deleting it would not have been a fix.

---

### [3] LOW — Twelve admin endpoints have no provisioning path

**Confidence:** high — verified by exhaustive search.

**Location:** `backend/core/models/user_model.py:50`.

**Evidence:** `is_admin` defaults to `false` at the database and **no code anywhere writes it** —
no endpoint, no script, no migration, no seed. Grep across `core/`, `scripts/` and
`alembic/versions/` returns only the column definition and the response field.

**Impact:** two-sided. The good half is that there is no privilege-escalation path: a student
cannot promote themselves by any route, which is the strongest possible answer to that question.
The bad half is that the entire Phase 4 admin surface — the twelve question-management endpoints
— is unreachable in every deployment, so the first administrator will be created by hand-written
`UPDATE users SET is_admin = true` against production at the moment someone needs it. Improvised
SQL against a live database under time pressure is how the wrong row gets updated.

**Not fixed** — this needs a product decision on how admins should be granted (a one-off script,
a bootstrap environment variable, or deliberately manual). Recommended: a `scripts/grant_admin.py`
taking an email, so the action is reviewable, logged and repeatable. Documented here rather than
chosen unilaterally.

---

## Findings added by the Phase 14 gate

Two further issues, both in the free tier, both reproduced live. Neither is a data-exposure
problem; both are spending controls that did not hold.

### [4] MEDIUM — the diagnostic consumed the daily grading allowance it is exempt from

**Confidence:** high — reproduced end to end.

**Location:** `backend/core/cruds/attempt_crud.py` (`count_graded_since`).

**Path:** new account → take the free diagnostic (the product's advertised first action) →
`graded_last_24h` reads 24 against a limit of 15 → every practice answer refused 402 for the next
24 hours.

**Evidence:** the counter had no session-type filter. `require_grading` correctly exempted
diagnostic *sessions* from the check, but the counter still counted diagnostic *answers*, so a
24-question sitting filled a 15-answer bucket. Measured on a fresh account: `can_grade_answer`
false, `can_start_practice` **true**, `practice_sessions_used` 0 of 3 — the interface would have
offered practice and then refused every answer with "you have used all 15 graded answers for
today" to a student who had used none.

**Impact:** the free tier's practice allowance was unreachable on day one, which is the day a
student converted from the landing page is most engaged. The core loop stopped at "practice", and
the paywall fired with the wrong reason — a grading wall that reads as a bug instead of the
practice-set limit, which is an honest upgrade moment. It also contradicted the documented intent
("The diagnostic is never capped by the grading limit").

**Fix:** the counter joins `sessions` and excludes diagnostics, so the counter agrees with the
exemption. Verified: after a full diagnostic, `graded_last_24h` is 0 and practice answers are
accepted; the cap still refuses the 16th practice answer, and the practice-set limit still
refuses a 4th set.

### [5] MEDIUM — free-tier limits were bypassable by concurrent submission

**Confidence:** high — reproduced live.

**Location:** `backend/core/controllers/attempt_controller.py` (`submit`).

**Path:** 20 simultaneous `POST /v1/sessions/{id}/attempts` → all 20 read the same pre-insert
count → all 20 pass the check → all 20 graded, against a limit of 15.

**Evidence:** every free-tier limit is a check followed by a write in a separate transaction.
Measured before the fix: 20 accepted, 0 refused, `graded_last_24h` 15 → 20. Each of those answers
is a paid model call, so this is a spending control that did not bind. The window is far wider
with a real provider, where a grading call takes seconds rather than milliseconds.

**Fix:** two parts. The counter now counts by **submission** rather than by completed grading, so
an answer is charged when the spend is committed rather than when it finishes — that alone closes
the sequential window. The check and the insert are then held together under a short per-user
Redis lock (`commons/locks.py`), which closes the concurrent one. The lock is per user, so there
is no cross-student contention, and it fails open on a Redis outage, matching the rate limiter's
documented posture: losing the counter store must degrade a spending control, never stop a
student answering. Verified: 20 concurrent submissions now yield exactly 15 accepted and 5
refused with `grading_limit_reached`.

**Residual, not fixed — the practice-set ceiling is enforced at the wrong point.**
`require_practice` runs when a set is *started*, but `count_practice_sets_answered` counts sets
that have been *answered*. A set that is started and not answered therefore costs nothing and
counts nothing, which is deliberate and documented. The consequence is that a client which starts
many sets before answering any of them can end up with more than three answered sets — a lock
does not fix this, because it is a semantic gap rather than a race. Daily spend remains bounded by
`FREE_DAILY_GRADED_ATTEMPTS`, which is now enforced atomically, so the exposure is a slower
accumulation rather than an unbounded one. Closing it properly means deciding where the set
allowance belongs — checked again on the answer path, or counted from started rather than
answered sets — which is a product decision about what a "used" practice set means, so it is
recorded here rather than chosen unilaterally.

---

## Verified sound

Each of these was tested against the running stack, not read and assumed.

**No cross-account access exists anywhere.** Two accounts, every object-scoped route. Sessions,
session results, session questions, attempt detail, attempt flagging, answer submission and
session completion all return **404** to a signed-in non-owner — not 403, so the existence of
another user's object is never confirmed — and **401** to an anonymous caller. Submitting to
another user's session with a fully valid body returns 404, so the ownership check is not merely
sitting behind schema validation.

**Question protection holds (invariants 2 and 9).** The pre-submission payload carries exactly
`id`, `prompt`, `category_slug`, `category_name`, `subcategory`, `difficulty` and
`question_version_id` — no `ideal_answer`, no `expected_concepts`, no `common_mistakes`, no
rubric. Requesting a question that exists but is outside your own session's composition returns
404 even when the session is yours, so owning one session does not let you walk the bank. The
review list carries no answer text and no reference answer. The rubric itself is never returned
by any endpoint, before or after submission.

**Admin routes return 404, not 403, to an ordinary user**, and 401 to an anonymous one. The
dependency is on the router, so an endpoint added later cannot be left unprotected by omission.

**Stripe webhooks cannot be forged.** The route reads `await request.body()` — the raw bytes the
signature covers — and verifies through `stripe.Webhook.construct_event`, which checks the HMAC
and rejects a stale timestamp. With no signing secret configured the endpoint answers **503 and
refuses every request**, which is the correct fail-closed direction; an unverified payment event
is not a payment event. Idempotency is a unique constraint on (provider, event ID) with the
insert deciding whether a delivery processes, not a check-then-write. Out-of-order deliveries are
rejected against `subscriptions.last_event_at`. Status codes are correct as instructions to
Stripe: 400 for a bad signature so it stops retrying, 5xx for a handler failure so it does.

**Entitlements cannot be granted by a client.** No endpoint sets a plan or extends access; the
webhook is the only writer. Gates are server-side, evaluated before the work is done, and return
402 carrying the reason and the numbers.

**Analytics cannot be poisoned.** Only `landing_view` and `paywall_reached` are accepted from a
browser; `checkout_completed`, `user_signed_up` and `diagnostic_completed` were each asserted
from an authenticated client and each returned `{"status": "ignored"}`. Properties are an
allowlist of scalars with a length cap, so an attempt to smuggle answer text and an email address
through an accepted event dropped both.

**Authentication.** Access token is a 15-minute HS256 JWT in an `HttpOnly` `SameSite=Lax` cookie
carrying no authorisation claims — admin rights and account status are read from the database on
every request, so suspension takes effect immediately. Refresh token is opaque, 384-bit,
SHA-256 hashed at rest, and rotated on use. **Theft detection was reproduced**: replaying an
already-rotated token revokes the whole family, and the victim's current token is rejected
afterwards. Passwords are Argon2id with transparent rehash on parameter hardening. Enumeration is
closed on both sign-in (one message for both failures, plus a dummy hash so timing does not
distinguish them) and registration.

**Rate limiting cannot be evaded by header forgery.** This was the one control I expected to
fail. `client_identifier` reads the leftmost `X-Forwarded-For` entry, which is the classic
bypass when a proxy *appends*. Tested directly: three requests carrying three different forged
`X-Forwarded-For`, `X-Real-IP` and `Forwarded` values all landed in **one** Redis bucket keyed on
the real peer, with the counter at 3. Caddy overwrites the header. See the deployment note below.

**Invariant 8 holds.** A `user_id` in a request body is ignored; `PATCH /v1/profile` carrying
another user's ID updated the caller's own row.

**Data export and deletion work.** Export returns the account, profile, sessions, attempts, skill
scores and grade flags, and contains no password hash and no rubric content. Deletion requires
the literal phrase `DELETE` *and* the current password, invalidates the session immediately, and
login afterwards fails. Recruiting consent defaults to `false` on a fresh account (invariant 7).

**Injection.** Every query is built from SQLAlchemy constructs; there is no string interpolation
into SQL anywhere. No `pickle`, `eval`, `exec`, `yaml.load` or `subprocess` in the application.
The one `eval` is `redis.eval` running a Lua compare-and-delete for lock release. The frontend has
no `dangerouslySetInnerHTML`, no `innerHTML` and no `eval`, and no client component reads
`process.env`; the only public variable is `NEXT_PUBLIC_API_PATH`, a path.

**Prompt injection.** The student answer is fenced with a per-request 64-bit random nonce, so the
closing delimiter cannot be forged; control characters are stripped; length is bounded three
times over (schema, database, prompt builder); the rubric is established before the untrusted
text; and the output schema is fixed and validated against the rubric afterwards, so nothing a
student writes can add a field or invent a concept key.

**Secrets and logging.** `.env` is gitignored and untracked; `.env.example` holds only
placeholders. No log statement writes a password, token, API key, prompt or rubric — the matches
for those words are all messages *about* a secret, never a value.

**Containers.** Production Compose publishes only the proxy's 80 and 443. Confirmed from the host:
the API (8000) and web (3000) ports are closed, so the API is reachable only through the proxy and
its headers. Postgres and Redis are published on loopback **only** by the development override.
Both application images run as non-root uid 1001. The proxy sets HSTS, `X-Content-Type-Options`,
`X-Frame-Options: DENY`, `Referrer-Policy` and `Cross-Origin-Opener-Policy`, and strips `Server`.

**CORS** is added only when `CORS_ORIGINS` is non-empty, which it is not by default — the app is
same-origin behind the proxy, so there is no CORS surface to misconfigure. Interactive docs and
the OpenAPI schema are disabled in production. Unhandled exceptions become a generic 500 with the
detail logged and never returned.

---

## Open items

Ordered by what I would do first. None blocks launch.

**1. Provision admins deliberately (finding 3).** Add `scripts/grant_admin.py` before the admin
surface is first needed, rather than during the incident that needs it.

**2. Install the missing scanners in CI.** `pip-audit` and `osv-scanner` would cover Python
dependency advisories, which nothing currently checks. `gitleaks` in CI is the durable answer to
secret hygiene, rather than the manual check done here.

**3. Redis is unauthenticated on the Compose network.** `redis-server` runs with no
`requirepass`. It is not published in production and holds no source-of-truth data — rate-limit
counters, job locks, dedupe keys and cache — so the blast radius of a compromise is resetting
rate limits and breaking job locks, not data loss. Worth `--requirepass` when convenient; it
needs a coordinated `REDIS_URL` change across api, scheduler and every existing `.env`, which is
why it is recommended rather than applied here.

**4. The per-IP rate limit depends on the proxy overwriting `X-Forwarded-For`.** It does today,
and the limit is verified sound. But the documented deployment target is EC2, and putting an ALB
or CloudFront in front of Caddy changes this: Caddy would then need `trusted_proxies` to identify
the real client, and with a proxy chain the leftmost `X-Forwarded-For` entry becomes
client-controlled again — which is exactly what `client_identifier` reads. Treat "the edge
overwrites `X-Forwarded-For`" as a deployment invariant and re-test this probe after any topology
change. The tight limit is per-account and unaffected either way; registration, at 20/hour, is
per-IP only and is what would be exposed.

**5. No breached-password check.** Minimum length is 10 with Argon2id, which is above the NIST
SP 800-63B floor, and composition rules are correctly absent. The control that guidance actually
recommends — screening against a breached-password list — is not implemented, so `aaaaaaaaaaaa`
and `password12345` are accepted.

**6. The OpenAPI document declares no security scheme**, so the published spec does not mark
which routes require authentication. Cosmetic only, and unreachable in production where the
schema is disabled.
