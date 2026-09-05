# Checkpoint — Phase 7: Practice engine

**Completed:** 2026-09-04
**Goal:** 5/10/20 sets, adaptive selection, weakness weighting, spaced repetition, difficulty
progression, recommendation explanation and a practice summary — with selection that is
deterministic and explainable, and edge cases tested.

---

## What was built

### Backend

| Area | Delivered |
|---|---|
| Selection | Weighted sum of four named signals: review due (100), weakness (60), novelty (25), difficulty fit (15) |
| Spaced repetition | Derived from attempt history — 2/7/21 day intervals by attempt count, 65 as the miss threshold |
| Cooldown | A question answered well is excluded for 21 days |
| Spread | 40% caps per category *and* per difficulty; the category cap lifts on request, the difficulty cap never does |
| Determinism | Selection is a pure function of history and bank; a hash tie-break keeps sets per-student |
| Explanation | Written at selection time and stored on the session |
| CRUD | `list_question_history` — one aggregated row per question, rather than hydrating every attempt |
| API | `POST /v1/practice`; sessions, answers and results reuse the diagnostic's endpoints |
| Labels | Graded attempts return readable names for the keys in *that grade* only |

### Frontend

`/practice` set chooser, `/practice/[id]` runner with per-question grade reveal, and
`/practice/[id]/summary`. `GradePanel` renders score, band, concepts shown and missed, mistakes,
coaching and a collapsed reference answer. The results and dashboard recommendations now link to a
real practice session.

---

## Verification

### Automated

```
backend  pytest                 442 passed  (was 399; +43)
backend  ruff / mypy            All checks passed / no issues in 88 source files
web      vitest                 80 passed   (was 65; +15)
web      eslint / tsc / build   clean / clean / 17 routes
```

New suites: `test_practice.py` (41), `PracticeRunner.test.tsx` (14), plus label-scope tests added
to `test_attempts.py`.

### End to end over HTTP

27 of 27 checks passed:

```
sizes 5 / 10 / 20                 201, correct counts
size 7, size 0, negative          400
unknown category                  400
rationale stored and returned     "no graded evidence yet" for a new student
  new_count                       whole set
  no rubric content               clean
  ordering                        easiest first
submit and poll                   graded, score in range
  concept labels supplied         readable
  labels cover only this grade    exactly the graded keys
  reference answer                revealed after submitting
category focus                    single category, "You asked to practise"
starting again                    new set, previous abandoned
engine-chosen 10-set              no category above 4, at least three categories
composition                       deterministic across two runs
anonymous                         401
```

### Browser

Followed the dashboard's "Practise Valuation" recommendation through to a graded answer. The
category arrived preselected from the link, the rationale read *"DCF is currently your weakest
category at 0, and 4 questions are new to you"*, and the grade panel showed score, band, concepts
with readable names, mistakes, coaching and a collapsed reference answer. The summary page
rendered with per-category breakdown.

---

## Problems found and fixed

1. **A real leak, caught by an existing test.** Adding readable concept labels to the graded
   response initially returned labels for *every* declared concept and mistake — the question's
   complete answer key, including the mistakes the student never triggered. Phase 5's
   `test_the_rubric_is_never_returned` failed immediately. It matters more than it looks: spaced
   repetition brings missed questions back, so a student could have memorised the checklist rather
   than learning. Labels are now restricted to the keys present in that grade, with two tests
   pinning it.

2. **Every practice set was flat.** End-to-end verification returned `[3, 3, 3, 3, 3]` — five
   questions at identical difficulty. Difficulty fit is the only signal separating otherwise-equal
   candidates, so a student with no history got every question at the level nearest their assumed
   mastery. Defensible ranking, worse session, and not the "difficulty progression" this phase
   asks for. Added a per-difficulty spread cap mirroring the category one; the same set now
   returns `[2, 3, 3, 4, 4]`.

3. **The practice summary said "This diagnostic".** `CategoryBreakdown` renders on both surfaces
   and had the word hardcoded, so the practice summary made a false statement about itself.
   Neutralised to "This session", with a test that fails if either name comes back.

4. **`useRef(Date.now())` failed the purity lint rule.** Reading the clock during render is impure;
   moved into an effect.

5. **Fake timers and `waitFor` deadlocked the runner tests.** Four tests could not see the grade
   reveal because `vi.useFakeTimers` and `waitFor`'s own polling fought each other. Switched to
   real timers with a generous timeout and shortened the poll interval to 1s, which is also better
   UX. The file runs in 4.8s.

6. **A test that asserted the wrong thing.** I wrote one claiming a well-answered question
   "returns after the cooldown" and asserted it appeared in a 20-set. It does not — leaving
   cooldown means it stops being *excluded*, after which it still loses to 40 unseen questions,
   which is the right ordering. Split into two tests: one for the exclusion rule against a small
   bank, one pinning that an unseen question outranks it.

---

## Design decisions

**Four named signals, not a model.** The PRD requires V1 selection to be deterministic and
explainable, and the interface makes a specific claim — *"Valuation is your weakest category, and
2 previous misses are due for review"*. That sentence is only honest if selection genuinely worked
that way. Weights are deliberately far apart rather than finely tuned: the ordering between
signals is the product decision, and false precision would invite tuning noise into something that
has to stay explainable.

**The rationale is written once and stored.** Deriving it at render time would make it drift —
mastery moves as a student practises, so a sentence recomputed later would describe a state that
no longer produced the set.

**Two spread caps.** One per category, because a set entirely from the weakest area is the
literally correct answer to "what is weakest" and a poor session — one sitting on one topic
produces fatigue rather than coverage. One per difficulty, for the reason problem 2 above made
concrete. Both fall back to overflow when a thin bank cannot fill the set within them, so the
promise of "10 questions" survives.

**A well-answered question is excluded outright for 21 days**, not merely deprioritised.
Re-testing something a student has just demonstrated is the clearest way to waste a slot in a
five-question set.

**Practice reveals grades per question; the diagnostic does not.** Established in Phase 6 and
completed here. Learning from a single answer is the point of practice, and deferring the feedback
would turn a study tool into a second assessment.

**Starting practice always creates a new set.** Unlike the diagnostic, there is no resume: a
student choosing "10 on Valuation" is asking for a new set, and silently handing them an older
half-finished one answers a different question.

**Set-level score is not shown as mastery.** The summary reports the set's own average separately
from category mastery. A good ten-question run moves a recency-weighted score a little; showing
the run's average as readiness would let it read as mastery the student has not earned.

---

## Honest scope statement

- **Selection quality has not been validated against real usage.** The weights, the 65 threshold,
  the 21-day cooldown and the 40% caps are reasoned defaults, tested for the behaviour they are
  supposed to produce. Whether they produce *good practice* is a question only real students can
  answer.
- **Spaced repetition intervals are approximate and per-question, not per-concept.** A student who
  misses the same concept across three different questions gets three separate schedules. Concept-
  level scheduling is a larger change and the PRD explicitly says to keep this simple until usage
  proves otherwise.
- **No free-tier limit.** A student can start unlimited practice sets, each costing grading calls.
  Entitlement gating is Phase 9 and this is the surface that most needs it.
- **No "Flag this grade" control**, still. The grade panel is the natural home for it and the API
  does not exist.
- **The browser pass scored 0 throughout**, because the fake grader matches terms and the concept
  labels for judgement questions are abstract phrases. That is the fake provider's limitation, not
  a grading result worth reading.
- **`list_question_history` uses raw SQL** (`DISTINCT ON` plus a window function). It is the one
  place in the CRUD layer that does, justified by pulling three numbers per question instead of
  every attempt's full text.
- **Practice sessions are not listed anywhere.** A student can reach a summary only by finishing a
  set or keeping the URL; history and review are Phase 8.
- **No E2E suite.** Still a script plus a manual browser pass.

---

## Blockers

None.

---

## Next

**Phase 8 — Review and progress.** The review list and detail, filters, the "practise this" action
from a specific past answer, mastery trends over time, and the dashboard's history section. Every
graded attempt the diagnostic and practice now produce becomes reviewable evidence.
