# Performance review — Phase 13 pass

**Date:** 2026-09-05
**Rule followed:** measure first, fix what the measurements show, change nothing that the
measurements do not justify.

---

## Summary

One real bottleneck was found and fixed: an N+1 query pattern across four endpoints, which made
the cost of a page scale with the number of rows on it. Query counts on the worst endpoint fell
from **54 to 8**, and measured latency from **77ms to 19ms**.

Everything else measured within budget. The frontend, the indexes, Redis and the scheduler
needed no changes, and this document records the numbers that say so — an unmeasured area is the
useful part of a performance report, so the measurements that found nothing are listed too.

---

## Method, and one methodology correction

The running stack is the **development** configuration: Next in dev mode and uvicorn with
`--reload`. Frontend numbers taken from it are meaningless for production, and the first
measurements showed the landing page at 120ms — which would have sent me optimising a page that
is fine. A production build was measured separately, against the standalone server, and it is
**5x faster**. The dev figures are kept below only to show the size of that gap.

| Page | dev p50 | **prod p50** | prod p95 |
|---|---|---|---|
| `/` (landing) | 120ms | **23ms** | 33ms |
| `/pricing` | 85ms | **15ms** | 18ms |
| `/signin` | 61ms | **13ms** | 15ms |

The API numbers below come from the dev container, which runs `--reload`. That adds a file
watcher, not per-request work, so they are representative — and in any case the *relative*
before/after comparison is what the fix is judged on, both measured the same way.

Query counts were taken by attaching a SQLAlchemy `before_cursor_execute` listener and calling
the real controllers against a realistic account: one completed 24-question diagnostic plus a
completed 20-question practice set, 44 graded attempts in total.

---

## The finding: N+1 on four endpoints

Every endpoint that rendered a *set* of questions fetched each question and each question version
one row at a time, inside a loop.

| Endpoint | Queries before | Queries after |
|---|---|---|
| `GET /v1/sessions/{id}` (24 questions) | **52** | **6** |
| `GET /v1/diagnostic` (current) | **54** | **8** |
| `GET /v1/review` (page of 20) | **43** | **5** |
| `GET /v1/review` (page of 5) | 13 | **5** |
| `GET /v1/sessions/{id}/results` | 38 | **15** |
| `GET /v1/progress` | 3 | 3 |
| `GET /v1/attempts/{id}` | 6 | 6 |

Measured latency, same account, 20 samples each:

| Endpoint | p50 before | p50 after | change |
|---|---|---|---|
| `GET /v1/sessions/{id}` | 77ms | **19ms** | −75% |
| `GET /v1/diagnostic` | 74ms | **25ms** | −66% |
| `GET /v1/review` | 73ms | **20ms** | −73% |
| `GET /v1/sessions/{id}/results` | 68ms | 61ms | −10% |
| `GET /v1/auth/me` (unchanged) | 7ms | 8ms | noise |
| `GET /v1/progress` (unchanged) | 11ms | 14ms | noise |
| `GET /v1/entitlements` (unchanged) | 19ms | 23ms | noise |

The three unchanged endpoints moved by ±4ms, which is the noise floor of this measurement. The
changed endpoints moved by 50ms or more, far outside it.

**Why it mattered more than the raw milliseconds suggest.** Latency tracked query count almost
linearly at about 1.4ms per query, so the shape of the problem was that cost scaled with content:
a page of 20 review rows cost 43 queries, and a 24-question session cost 52. `GET /v1/sessions/{id}`
is read on **every question of a 24-question sitting**, so it was the single hottest authenticated
path in the product. Two further multipliers were waiting: each request held a pooled connection
for the whole serial chain, so throughput under load was bounded by round trips rather than work;
and on RDS — the documented migration target — per-query network latency is roughly 1ms rather
than 0.2ms, which would have turned 52 queries into about 50ms of pure waiting.

**The fix.** `CRUDQuestion.map_by_ids` and `CRUDQuestionVersion.map_by_ids` read a whole set in
one round trip and return a mapping, so callers keep their own ordering — which is the stored
composition order, not anything the database would produce. Three call sites now use them:
`SessionController.get_state`, `SessionController._category_results` and
`ReviewController.list_attempts`.

The counts are now **constant** rather than proportional: a page of 5 and a page of 20 both cost
5 queries, and a session costs 6 whether it holds 5 questions or 24.

This was not a new idea in the codebase — `ReviewController` already batched grade flags, with a
comment reading "One query for every flag, rather than one per row." The questions and versions
beside it had simply never been given the same treatment.

The single-object lookups (`GET /v1/attempts/{id}`, the admin detail endpoints, the grading
service) were deliberately left alone. They fetch one row because they render one row.

---

## Measured and left alone

**The frontend is not a bottleneck.** 23ms for the landing page in production, including a
server-side call to the plan catalogue. The `force-dynamic` on `/` costs roughly 10ms over
`/signin`, which is that API round trip, and it buys a real product guarantee — a plan that is
not on sale is never advertised. Not worth trading for static rendering.

**Indexes are correct and used.** `EXPLAIN ANALYZE` on the review query plans a sequential scan
at the current table size, which is the right choice for 204 rows. Forcing the planner off
sequential scans confirms both relevant indexes are viable for the query shape:
`ix_attempts_user_submitted` for the keyset page, and the partial index
`ix_sessions_user_in_progress` for the diagnostic-exclusion subquery added in Phase 12, with
`type` as a cheap recheck on a one-row result. Every foreign key is indexed.

**`GET /v1/sessions/{id}/results` is the slowest endpoint at 61ms**, and was left that way. It
recomputes mastery on every read, which is 8 `skill_scores` upserts. That looks wasteful until
you check when it runs: while grading is in flight the endpoint returns before the recompute, so
the client's polling does not trigger it. It runs when a student opens their results — once or
twice per session. 61ms for that is not a bottleneck, and making it conditional would add state
to buy nothing measurable.

**Connection pool: 75 of 100.** Production runs `--workers 4`, and each worker is a separate
process with its own pool, so the real arithmetic is `4 x (10 + 5) + 15 = 75` against Postgres's
default `max_connections = 100`. That is safe but has no documented margin, and the obvious
response to load — more workers — silently exceeds it, surfacing as
`FATAL: sorry, too many clients already` on random requests, which reads like an application bug.
The numbers were not changed; the arithmetic is now a comment beside the `--workers` flag, which
is where someone will be standing when they change it.

**Redis is healthy and small.** 1.76MB used, 1.87MB peak, 13,741 keyspace hits against 0 misses,
34 keys expired, **0 evicted**. Every key carries a TTL and the rate-limit counters expire
correctly. No change made.

**The grading retry sweep is bounded and sequential** — a `limit` per run, processed one at a
time. That is a deliberate cost throttle on a paid API and should stay one.

---

## Open items

Not fixed, because nothing measured justifies fixing them yet. Recorded with the trigger that
would change that.

**1. Mastery reads a user's entire graded history.** `list_graded_for_mastery` has no time bound,
then `calculate_weighted_score` discards everything outside a 365-day window in Python. Correct,
and irrelevant at a scale where a student uses this for one recruiting season. Pushing the window
into the query would need an index on `(user_id, graded_at)` — a migration for a problem nobody
has. Revisit if any user exceeds a few thousand attempts.

**2. Inline grading has no concurrency cap.** Each submission dispatches a background task with no
semaphore, so a burst of simultaneous submissions becomes a burst of concurrent provider calls.
The calls are async and do not block other requests, and provider 429s are already handled by the
retry path, so there is no measured problem. A cap becomes worth adding when real traffic shows
provider throttling or cost spikes, not before.

**3. Redis has no `maxmemory`.** Unbounded in principle; 1.76MB and zero evictions in practice,
because every key has a TTL. If it is ever set, pair it with `noeviction` rather than an LRU
policy: every consumer in this application already degrades safely when a Redis command fails
(the rate limiter fails open by design, a job lock simply is not acquired and the job runs next
interval), whereas silent eviction of a job lock would let two schedulers run the same job.

**4. Container resource usage was not measured.** The Docker socket is not accessible from this
session, so `docker stats` could not be run. Memory and CPU per container remain unmeasured
rather than assumed fine.

**5. `pg_stat_statements` is available but not loaded.** It needs `shared_preload_libraries` and a
restart. Worth enabling before the first real load test; query counts here came from application
instrumentation instead, which measures the same thing from the other side.

---

## Verification

602 backend tests passing (5 batch-loader tests added), frontend typecheck, lint and 154 tests
clean, `ruff` and `mypy` clean. The full diagnostic funnel produces an identical result after the
change, and the Phase 12 mid-diagnostic protections were re-probed and still hold.
