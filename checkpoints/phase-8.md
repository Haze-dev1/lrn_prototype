# Checkpoint — Phase 8: Review and progress

**Completed:** 2026-09-04
**Goal:** review list, review detail, filters, a practise-this action, category mastery, mastery
trends, the dashboard and the recommendation card — without dashboard bloat.

---

## What was built

### Backend

| Area | Delivered |
|---|---|
| Review list | `GET /v1/review` — filters on category, score, missed concept, flagged, recency; keyset paginated |
| Review detail | The attempt endpoint, extended with the student's own answer and whether they flagged it |
| Grade flags | `POST /v1/attempts/{id}/flag` — five reasons, idempotent, graded attempts only |
| Progress | `GET /v1/progress` — per-category mastery, weekly trend, movement, weakest and strongest |
| Trend | `MasteryService.trend_for_user` — reconstructed from attempt history, no new schema |
| CRUD | Review filters, JSONB containment for missed concepts, flag lookups in one query |

### Frontend

`/review` with URL-backed filters, `/review/[attemptId]` showing the student's own answer above
the grade with a practise-this exit, `/progress` with a mastery trend and per-category list, a
flag control on the grade panel, and a dashboard rebuilt to the PRD's hierarchy.

---

## Verification

### Automated

```
backend  pytest                 475 passed  (was 442; +33)
backend  ruff / mypy            All checks passed / no issues in 91 source files
web      vitest                 104 passed  (was 80; +24)
web      eslint / tsc / build   clean / clean / 20 routes
```

New suites: `test_review.py` (33) and `ReviewAndProgress.test.tsx` (24).

### End to end over HTTP

33 of 33 checks passed:

```
empty history                     empty page, not an error
progress with no evidence         8 categories, every score null, overall null, movement null
after five graded answers         review lists all five
  item carries score and band     yes
  item carries no answer text     confirmed
  no rubric content anywhere      confirmed
filters                           category, score, recency, flagged, missed-concept all narrow
unknown category                  400
detail                            returns the student's own answer and the reference answer
flag                              201; second flag returns the existing one
  attempt reports flagged         yes
  flagged filter finds it         yes
  invalid reason                  422
progress after evidence           measured categories, overall, weakest, trend all present
  unmeasured still null           confirmed
another student                   sees none of it; cannot flag it (404)
anonymous                         401 on both surfaces
```

### Browser

Walked the dashboard, review list, review detail and progress. The dashboard follows the PRD's
hierarchy — overall, weakest area, one recommended action, the trend, then recent answers — and
the trend panel correctly said "Not enough history yet" rather than drawing a line through a
single point. Review detail showed the student's own answer above the grade with the flag control
beneath it.

---

## Problems found and fixed

1. **The review detail page had no answer to review.** The graded attempt response never included
   the student's own text — the practice runner does not need it, because the answer is still on
   screen. Weeks later on a review page it is the thing being reviewed, and a score without it is
   readable but not reviewable. Added to the graded response only.

2. **The suite had slowed from 76s to 163s.** Rather than let it drift, I measured: three grading
   tests were each sleeping three real seconds through the immediate-retry backoff. An autouse
   fixture zeroing it took that file from 13s to 3.6s. The remaining cost is diagnosed and
   recorded below rather than papered over.

3. **Two review tests were written badly and rewritten.** One used a convoluted round trip through
   `/auth/me` to find the user it had just created; another imported symbols it never used. Both
   caught on my own review before the gate.

---

## Design decisions

**The trend is reconstructed, not stored.** Mastery is already a pure function of (graded
attempts, reference time), so the value at any past date can be recomputed by running the same
weighting over the attempts that existed then. That means no history table to keep in step, no
backfill for existing users, and no possibility of a stored trend disagreeing with the current
score it ends at. Each point sees only evidence graded by that date — a trend that could see the
future would show every student improving regardless of what they did.

**An unmeasured category is null, never zero.** This is the single most important rule on the
progress surface. "Not measured" and "measured badly" are different claims, and rendering the
first as the second invents a readiness signal the product has no basis for. It is enforced in the
response schema, the component, and a test on each.

**`movement` is null until there are two measured points.** A flat line and no data look identical
on a chart, and only one of them means the student has not moved.

**One sparkline of overall mastery, not eight lines.** The question is "am I improving", and eight
overlapping series answer it worse than one — the student would have to do the aggregation
themselves to get back to what they asked. Drawn as inline SVG rather than adding a charting
dependency for a single polyline.

**The review list carries no answer text.** A list is scanned rather than read; shipping every
answer would make the page heavy to load and heavy to look at. Full evidence lives on the detail
endpoint, opened one at a time.

**The flag control is understated and collapses once used.** It has to exist — a student who
believes a grade is wrong and cannot say so stops trusting every other grade — but a prominent
dispute button after every low score would turn the product into an argument. A flag is a
statement, not a vote, so raising it twice returns the existing one.

**Every review and progress surface ends in an action.** Each category row and each reviewed
answer links to practice for that category. Review that ends in reading is a reference page;
review that ends in doing is a study loop.

---

## Honest scope statement

- **There is no admin queue for flags.** Students can raise them and they are stored with a status
  and a reviewer column, but nothing surfaces them to an administrator and no one can resolve one.
  That workflow is §52 of the PRD and belongs with the rest of admin.
- **The backend suite takes ~2.5 minutes**, and roughly 40 tests each call `QuestionSeeder().run()`
  to get a full bank — about 240 small transactions per call. That is most of the runtime. The fix
  is a bulk test-bank helper, which I chose not to attempt at the end of a feature phase because
  swapping ~40 call sites to a different bank risks weakening what those tests actually cover.
- **The missed-concept filter has no index behind it.** It uses JSONB containment, which is
  GIN-indexable, but no index has been created. Fine at current volumes; it will need one.
- **The trend recomputes mastery per point on every progress load.** One query plus in-memory
  passes, cheap for one student's history, but it is work inside a GET and will want caching if
  progress becomes a hot path.
- **The trend window is fixed at eight weeks** with no way to change it, and points are weekly
  regardless of how much a student practised.
- **Concept keys are shown raw in the review list** ("6 concepts missed" is a count, but the
  missed-concept filter URL carries the key). The detail page resolves labels; the list does not.
- **No E2E suite.** Still a script plus a manual browser pass.
- **The browser pass scored 0 throughout** — the fake grader's term overlap does not credit
  recycled answers. Not a grading result worth reading.

---

## Blockers

None.

---

## Next

**Phase 9 — Billing.** Plans, Stripe Checkout and Customer Portal, the webhook, entitlement
lifecycle, server-side gating and free-tier limits. Practice is the surface that most needs a
limit: a student can currently start unlimited sets, each costing paid grading calls.
