# Checkpoint — Phase 6: Diagnostic

**Completed:** 2026-09-04
**Goal:** the 24-question diagnostic — deterministic server-side composition, session state,
answer submission, grading, results, category mastery and a recommended next action — with a
polished assessment UX, tested against refresh, network failure, duplicate submit, grading
failure, unauthorised access and ideal-answer protection.

---

## What was built

### Backend

| Area | Delivered |
|---|---|
| Composition | 24 questions, three per category, deterministic per student, difficulty ramping across the sitting |
| Failure mode | `CompositionError` with per-category shortfalls when the bank is thin |
| Session lifecycle | Start-or-resume, read state, complete, read results |
| Read-only lookup | `GET /v1/diagnostic`, so asking whether one exists does not create one |
| Results | Grading progress, per-category mastery, strengths, weaknesses, one recommendation |
| Mastery | Recomputed on the first complete results read, so results and dashboard always agree |

### Frontend

`/diagnostic` intro, `/diagnostic/[id]` runner, `/diagnostic/[id]/results`, and a rebuilt
dashboard. Progress rail, difficulty meter, answer composer, honest grading-progress panel, and
a results page ordered weakest-first. `Textarea` now forwards a ref.

---

## Verification

### Automated

```
backend  pytest                 399 passed  (was 361; +38)
backend  ruff / mypy            All checks passed / no issues in 87 source files
web      vitest                 65 passed   (was 30; +35)
web      eslint / tsc / build   clean / clean / 13 routes
```

New suites: `test_diagnostic.py` (35), plus `TestFakeProviderEndToEnd` added to
`test_grading_service.py`, and `DiagnosticRunner.test.tsx` / `ResultsHeadline.test.tsx` on the web.

### End to end over HTTP

28 of 28 checks passed against the running stack:

```
GET diagnostic before starting     null, and no session created
start                              24 questions, 8 categories, 3 each, resumed false
  no rubric content in payload     no ideal_answer / expected_concepts / rubric / thresholds
  difficulty ramps                 last eight harder than first eight
restart                            same session id, resumed true
complete with 1 answered           409
complete with 24 answered          200, status completed
answer a finished session          409
grading                            24 graded, 0 failed
results                            8 categories, 3 answers each, concept keys present
  recommendation                   targets the lowest-scoring category
  no rubric content                clean
another student reads session      404
another student reads results      404
anonymous start                    401
```

### Browser

Signed in, completed onboarding, started the diagnostic, answered a question by hand and the rest
through the session, resumed mid-sitting, finished, and read the results and dashboard. The
assessment renders without the application shell, shows question number, category, a subtle
difficulty meter, a 24-mark progress rail and a large composer — and **never a grade**. Resuming
landed on the correct question with prior answers intact.

---

## Problems found and fixed

Both of the real bugs were found in the browser, not by the test suite.

1. **The default provider reported concept keys the rubric did not declare.** The results page
   showed a category scored 100 with *no* concepts hit — arithmetically impossible, since the fake
   provider derives the score from the concepts it hit. Cause: its line parser had `:` inside the
   key character class, so a greedy match consumed the separator and produced `net_debt:`. The
   validation layer then correctly dropped every key as undeclared, exactly as designed, which is
   why nothing failed loudly.

   Every existing grading test drove a stub provider with hand-written keys, so none of them
   exercised a provider whose keys had to survive reconciliation. Three regression tests now do,
   and all three were confirmed to fail against the old regex. The real OpenRouter path was never
   affected — the Phase 5 live run showed `dropped=[]` — but the fake provider is the default, so
   anyone running locally saw zero concept detail everywhere.

2. **The results page claimed "Full concept coverage" beside a score of 0.** An empty
   `missed_concepts` list was being read as evidence of coverage, when it is also what a grading
   failure or a fully rejected key set produces. The claim is now made only where the score
   supports it; otherwise nothing is said. A student who reads a contradiction like that has no
   reason to trust anything else on the page.

3. **The database rejected a test fixture, correctly.** Two results tests tried to simulate
   "answered but not yet graded" by regressing a graded attempt, and
   `ck_attempts_ungraded_has_no_score` refused it. The constraint was right and the fixture was
   wrong; the tests now create ungraded attempts directly rather than trying to reach an
   impossible state.

4. **A `setState` inside an effect** reset the composer's draft on each question. Replaced with
   the same keying pattern used in Phase 4 — the parent keys the composer on the question ID, so
   a remount resets the draft and focus for free.

5. **An always-true assertion** (`... or True`) that I wrote and then caught on review. Replaced
   with one that tests the actual claim.

6. **One false alarm, checked rather than assumed.** A screenshot showed the submit button greyed
   out after typing a valid answer. Inspecting the DOM showed `disabled: false` — the capture had
   caught a mid-render frame. No change made.

---

## Design decisions

**The diagnostic never reveals a grade mid-sitting.** This is the largest product decision in the
phase and it is a deliberate departure from the generic grading UX in the PRD's §19. A diagnostic
is an assessment: showing a score after each answer would let a student calibrate as they go, turn
24 questions into 24 emotional beats, and spend the results page's payoff before they reach it.
Practice, where learning from each answer *is* the point, will reveal grades immediately.

**Difficulty ramps across the sitting, not within each category.** One easy question from every
category, then one medium, then one hard. A student weak in Accounting discovers that in the first
eight minutes rather than after grinding through three Accounting questions, and the assessment
reads as one thing rather than eight consecutive quizzes.

**Composition is deterministic per student, not globally fixed and not random.** A random draw
cannot be reproduced when a result is disputed. A single fixed set of 24 would circulate within a
week. A hash of the user and question IDs gives both properties at once.

**Results show stored mastery, not this session's mean.** Two surfaces must never disagree about
how ready a student is, so the headline number comes from `skill_scores` — recomputed on the first
complete results read — with the session's three scores shown beside it as the evidence.

**Completing does not wait for grading, and partial results are never shown.** Grading is
asynchronous and can outlast a student's patience for a spinner, so finishing is instant and the
results endpoint reports real progress. Until every attempt resolves it returns no scores at all:
a readiness number from half the evidence is a wrong number, not an early one. Failures are
terminal, so one bad model call cannot strand a student behind a spinner forever.

**The runner renders without the application shell.** The sidebar, the account link and the
navigation are all invitations to leave. This is the one surface where the student should have
nothing to look at but the question.

---

## Honest scope statement

- **No "Flag this grade" control.** §19 of the PRD calls for one; the grade-flag API does not
  exist and is not in this phase's scope list. A button with no backend would be a fake, so there
  is none. `grade_flags` remains empty.
- **The "Practise <category>" button on the results page links to the dashboard**, because
  practice does not exist until Phase 7. It is wired to a real destination rather than dead-ending,
  but it does not yet do what it says.
- **A student can retake the diagnostic freely.** There is no limit and no entitlement gate;
  free-tier limits are Phase 9. Each retake composes the same questions for that student.
- **Results were verified against the fake grader, not a live model.** The scores in the browser
  pass are near zero because recycled generic answers do not overlap the rubrics — that is the
  fake provider working as designed, not a grading result worth reading.
- **No E2E suite.** Playwright is still unconfigured; the end-to-end evidence is a script plus a
  manual browser pass.
- **Mastery recomputation runs inside a results read.** It is idempotent and cheap at this scale,
  but it is work happening in a GET, and it will want moving if results become a hot path.
- **The dashboard is not the Phase 8 dashboard.** It answers where you are, what is weakest and
  what to do next, and shows the category breakdown. Trends over time, review and history are
  Phase 8.
- **Skipping is allowed but not surfaced as a concept.** A student can skip and return via the
  progress rail, but there is no "skipped" state — an unanswered question simply looks unanswered.

---

## Blockers

None.

---

## Next

**Phase 7 — Practice engine.** 5/10/20 sets, weakness weighting, spaced repetition at roughly 2,
7 and 21 days, difficulty progression, and a human-language explanation of why each session was
composed the way it was. The diagnostic now produces the mastery signal that practice selects
against, and the "Practise this" action finally gets a real destination.
