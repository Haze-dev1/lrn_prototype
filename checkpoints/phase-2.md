# Checkpoint — Phase 2: Database + Domain Foundation

**Completed:** 2026-09-03
**Goal:** the full domain schema, migrations, CRUD layer, and initial domain services.

---

## What was built

| Area | Delivered |
|---|---|
| Models | 13 tables across 7 model modules, with CHECK constraints, partial indexes and FK indexes |
| Migrations | `initial_schema` + `seed_categories`, both reversible; round-trip verified |
| Reference data | The eight agreed categories, seeded by migration |
| CRUD | 8 CRUD classes over 7 modules, Eigi layering, every method docstringed and logged |
| Domain service | `MasteryService` — recency-weighted mastery, wired into the nightly scheduler job |
| Tests | 69 backend tests, 55 of them integration tests against a real PostgreSQL |
| Enums | `core/constants/enums.py` — 14 `StrEnum`s that generate the database CHECK constraints |

### Tables

`categories` · `users` · `profiles` · `questions` · `question_versions` · `sessions` ·
`session_questions` · `attempts` · `grade_events` · `skill_scores` · `subscriptions` ·
`entitlements` · `grade_flags`

Two tables beyond the PRD's list, both load-bearing rather than speculative:

- **`categories`** — a reference table, not an enum, because the product displays a human name and
  a fixed order for each category, and both questions and skill scores key off them.
- **`session_questions`** — the server-decided composition must be persisted or a browser refresh
  cannot recover an in-progress session, and nothing stops a client reshuffling to farm easy
  questions. Attempts cannot serve this: an attempt row only exists after submission, so the
  unanswered remainder of a session would be unknown.

---

## Verification — commands run and their actual output

### Migrations

```
alembic upgrade head        -> initial schema, then seed categories
tables created              -> 14 (13 + alembic_version)
categories seeded           -> 8 rows, display_order 1-8
alembic downgrade base      -> 1 table remaining
alembic upgrade head        -> 14 tables, 8 categories (round-trip clean)
alembic check               -> "No new upgrade operations detected."  (models match schema)
```

Autogeneration preserved everything hand-written: **7 partial indexes** with their `WHERE`
clauses, **42 CHECK constraints**, and **11 `uuidv7()` server defaults**.

### The constraints actually reject bad data

Verified directly in `psql`, so the guarantee is proven at the database rather than inferred from
the code that usually writes it:

```
UPDATE attempts SET grading_status='failed', score=0 ...
  ERROR: violates check constraint "ck_attempts_ungraded_has_no_score"

UPDATE attempts SET grading_status='graded' ...              (no score)
  ERROR: violates check constraint "ck_attempts_graded_has_result"

UPDATE attempts SET grading_status='graded', score=82, band='strong', graded_at=now() ...
  UPDATE 1                                                    (legitimate path still works)
```

That last line matters: it shows the tests are not passing because everything is rejected.

### Indexes are used by the queries they were designed for

`EXPLAIN (ANALYZE, BUFFERS)` against 500 users / 2,000 questions / 10,000 attempts:

| Query | Plan | Time |
|---|---|---|
| Review list — attempts by user, newest first | `Index Scan Backward using ix_attempts_user_submitted` | 0.103 ms |
| Spaced repetition — per user + question | `Index Scan Backward using ix_attempts_user_question_submitted` | 0.240 ms |
| Grading retry sweep — unresolved only | `Index Scan using ix_attempts_unresolved_grading` | 0.102 ms |
| Question selection — active by category + difficulty | `Bitmap Index Scan on ix_questions_active_selection` | 0.230 ms |

No sequential scans on the hot paths.

### Tests

```
make test-api                      69 passed
backend, no database or redis      14 passed, 55 skipped   (skip guards work; no failures)
backend ruff check                 All checks passed!
backend ruff format --check        60 files already formatted
backend mypy core commons          Success: no issues found in 48 source files
web eslint / tsc / vitest          clean / clean / 9 passed
```

### Scheduler

```
job: scheduler_heartbeat    trigger=interval[0:00:30]
job: mastery_rollup         trigger=cron[hour='2', minute='30']
scheduler health: Up 14 seconds (healthy)
```

The Phase 1 placeholder `maintenance_job` is gone, replaced by a real lock-guarded rollup.

---

## Design decisions

**`uuidv7()` primary keys.** Verified native in the PostgreSQL 18.6 container and confirmed
time-ordered (consecutive values shared the `01a0682c-140b-7…` prefix). UUIDs keep IDs
non-enumerable so an attempt ID in a URL leaks no volume information; version 7 avoids the index
fragmentation random v4 keys cause on the fastest-growing tables. **This makes PostgreSQL 18 a
hard floor**, now documented in the README.

**Status columns are `text` + CHECK, not PostgreSQL `ENUM`.** Adding a value becomes a constraint
change instead of an `ALTER TYPE` that cannot be cleanly rolled back. `in_check()` generates the
SQL predicate from the `StrEnum`, so the constraint cannot drift from the Python type.

**Product invariants pushed into the schema.** A grading failure that becomes a score of 0, a
duplicate submit, a mastery score with no evidence behind it, a published question with no
rubric, two rubrics published at once — each corrupts evidence permanently and irreversibly, so
each is a CHECK or unique constraint rather than a controller check that a future code path might
forget.

**`subscriptions` and `entitlements` are separate tables.** The subscription mirrors what the
payment provider believes; the entitlement is what this application will actually allow. Keeping
them apart means a delayed, duplicated or out-of-order webhook updates the mirror without
silently granting or revoking access, and support can grant access without inventing a fake
subscription. `get_active_for_user` evaluates expiry against the current time, so an elapsed
Season Pass loses access immediately rather than waiting for a reconciliation job.

**Mastery is a recency-weighted mean**, half-life 30 days, 365-day evidence window, returning
`None` rather than 0 when there is no evidence. Simple enough to explain to a student who asks why
their score moved, which rules out anything more clever.

---

## Problems found and fixed

1. **A test was passing through a code path that could not produce the state it claimed to test.**
   `set_grade_result` forces status to GRADED, so asserting it could write a failed-with-score row
   was meaningless. Rewritten as raw SQL against the constraint — which is the right level anyway,
   since the guarantee must survive future code paths and manual fixes.

2. **`session` as a local variable shadowed the `session()` context manager** in several tests.
   Renamed to `session_row`; added to the CLAUDE.md pitfalls list.

3. **`make test-api` could not authenticate.** The conftest default pointed at credentials that do
   not match `.env`, so the TCP probe succeeded and the connection then failed — tests would error
   rather than skip. The target now derives the URL from `.env` and uses `<POSTGRES_DB>_test`.

4. **Session-scoped event loop needed for database fixtures**, for the same reason as Phase 1's
   Redis singleton: the engine is process-wide and a per-test loop closes underneath its pool.

5. **Alembic deprecation warning** about `path_separator`; set explicitly in `alembic.ini`.

6. **Removed a `make seed` target I had just added** for a `seeds.load_seed_data` module that does
   not exist. Question-bank content is Phase 4; documenting it now would have been fiction.

---

## Honest scope statement

Built and verified, but deliberately **not** claimed:

- **There is no question content.** The bank is empty; only the eight categories are seeded.
  Authoring, import and admin management are Phase 4.
- **No authentication.** `users` has `password_hash` and `google_sub` columns and the constraint
  that an account keeps a way to sign in, but nothing hashes a password or verifies a token yet.
  Phase 3.
- **No API routes** beyond health. No controllers, no request/response schemas. CRUD and models
  are exercised directly by tests, not over HTTP.
- **`MasteryService` is not yet reachable by any user-facing surface.** It is scheduled nightly
  and unit-tested; the dashboard that reads it is Phase 8.
- **The grading retry sweep query exists** (`list_due_for_retry`) but no job calls it — the
  grading pipeline it serves is Phase 5.
- CRUD methods were written for the paths Phases 3-9 will use. Those not yet exercised by a
  caller are covered by tests, not by production use.

---

## Blockers

None.

---

## Next

**Phase 3 — Auth + onboarding.** Argon2id registration and login, JWT access/refresh in HttpOnly
cookies, Google OAuth, session verification middleware, onboarding (school, graduation year,
target role), recruiting consent, and account data export and deletion — followed by a security
review of the authentication and authorization surface.
