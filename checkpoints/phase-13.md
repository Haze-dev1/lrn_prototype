# Checkpoint — Phase 13: Performance and scalability pass

**Completed:** 2026-09-05
**Goal:** measure frontend load, API latency, indexes, query count, connection usage, Redis,
scheduler behaviour, grading concurrency and retries — then fix actual bottlenecks and add no
premature infrastructure.

Full measurements: `docs/performance-review.md`.

---

## Outcome

One real bottleneck, found by measurement and fixed. Query counts on the hottest authenticated
endpoint fell **54 → 8**, and its latency **77ms → 19ms**. Nothing else was changed, and the
report records the numbers that justify leaving each of them alone.

---

## The methodology correction that mattered

The running stack is the **development** configuration — Next in dev mode, uvicorn with
`--reload`. The first frontend measurements showed the landing page at 120ms, which would have
sent me optimising a page that is fine. Measuring a real production build instead:

| Page | dev p50 | **prod p50** |
|---|---|---|
| `/` | 120ms | **23ms** |
| `/pricing` | 85ms | **15ms** |
| `/signin` | 61ms | **13ms** |

Production is 5x faster. The frontend needed no work, and measuring the wrong thing would have
produced changes with no value.

---

## The finding: N+1 across four endpoints

Every endpoint rendering a *set* of questions fetched each question and version one row at a
time, inside a loop.

| Endpoint | Queries | Latency p50 |
|---|---|---|
| `GET /v1/sessions/{id}` (24 questions) | 52 → **6** | 77ms → **19ms** |
| `GET /v1/diagnostic` | 54 → **8** | 74ms → **25ms** |
| `GET /v1/review` (page of 20) | 43 → **5** | 73ms → **20ms** |
| `GET /v1/sessions/{id}/results` | 38 → **15** | 68ms → 61ms |

Three unchanged endpoints moved ±4ms across the same runs, which establishes the noise floor; the
changed ones moved by 50ms or more.

Latency tracked query count almost linearly at ~1.4ms per query, so the real problem was shape,
not milliseconds: cost scaled with content. `GET /v1/sessions/{id}` is read on **every question
of a 24-question sitting** — the hottest authenticated path in the product. Two multipliers were
waiting: each request held a pooled connection for the whole serial chain, capping throughput on
round trips rather than work; and on RDS, the documented migration target, per-query latency is
~1ms rather than ~0.2ms, turning 52 queries into ~50ms of pure waiting.

**Fix:** `CRUDQuestion.map_by_ids` and `CRUDQuestionVersion.map_by_ids` read a set in one round
trip and return a mapping, so callers keep the stored composition order. Applied at the three
loop sites; the single-object endpoints keep `get_by_id` because they render one row. Counts are
now constant — a page of 5 and a page of 20 both cost 5 queries.

The codebase already had this idea: `ReviewController` batched grade flags with the comment "One
query for every flag, rather than one per row." The questions beside them had never been given
the same treatment.

---

## Measured and deliberately left alone

- **Indexes are correct.** `EXPLAIN ANALYZE` plans a seq scan at 204 rows, which is right.
  Forcing the planner off seq scans confirms both indexes serve the query shape, including the
  partial `ix_sessions_user_in_progress` backing the Phase 12 diagnostic-exclusion subquery.
- **Results at 61ms is the slowest endpoint and stays.** It recomputes mastery per read, but
  polling never reaches that branch — it returns earlier while grading is in flight — so it runs
  once or twice per session. Making it conditional buys nothing measurable.
- **Connection pool: 75 of 100.** `4 workers x (10 + 5) + 15`. Safe, but undocumented and one
  `--workers` bump from exhaustion. Numbers unchanged; the arithmetic is now a comment beside the
  flag, where someone will be standing when they change it.
- **Redis:** 1.76MB, 13,741 hits / 0 misses, 0 evictions, every key expiring correctly.
- **Grading retry sweep** is bounded and sequential — a deliberate cost throttle on a paid API.

---

## Verification

| Check | Result |
|---|---|
| Backend suite | **602 passing**, 0 failures (5 batch-loader tests added to the 597 from Phase 12) |
| Frontend | typecheck, lint clean; 154 tests passing |
| `ruff` / `mypy` | clean |
| Full diagnostic funnel after the change | identical — 24/24 graded, 8 categories, weaknesses, explained recommendation, review 20 items |
| Phase 12 security fixes still hold | re-probed: review mid-diagnostic returns 0 items, `ideal_answer` only after completion |

---

## Open items

Recorded with the trigger that would change them, in `docs/performance-review.md`: mastery reads
a user's whole graded history (irrelevant at one-recruiting-season scale; needs a
`(user_id, graded_at)` index to fix, a migration for a problem nobody has); inline grading has no
concurrency cap (async, and provider 429s already retry); Redis has no `maxmemory` (pair it with
`noeviction`, not LRU, if ever set — every consumer already degrades safely on error).

**Not measured, and said so rather than assumed:** container CPU and memory, because the Docker
socket is not reachable from this session. `pg_stat_statements` is available but not loaded;
query counts came from application-side instrumentation instead.
