# Checkpoint — Phase 5: OpenRouter grading

**Completed:** 2026-09-04
**Goal:** provider abstraction, OpenRouter provider, grading service, structured schema
validation, retries, timeout handling, the attempt state machine, audit events, prompt-injection
defences, and cost and latency logging — then benchmark fixtures to validate grading behaviour.

---

## What was built

| Area | Delivered |
|---|---|
| Provider abstraction | `GradingProvider` interface; nothing above it knows OpenRouter exists |
| OpenRouter provider | Chat completions, JSON-schema constraint, usage, cost, latency, request ID |
| Fake provider | Deterministic term-overlap grading; the default, so a fresh clone works |
| Grading service | Prompt → call → validate → persist → audit, with every failure path covered |
| Validation | Shape, rubric-reconciled keys, derived band, wrapped-JSON tolerance |
| Retries | Immediate in-call retry for transient failures; scheduled sweep for durability |
| Attempt state machine | `pending → grading → graded`, or back to `pending`, or `failed` |
| Audit | A `grade_event` per call — success or failure — with provider, model, versions, usage, cost, latency, validation status |
| Injection defences | Per-request nonce fence, fixed output schema, explicit framing |
| Submission API | `POST /v1/sessions/{id}/attempts`, `GET /v1/attempts/{id}` |
| Scheduler | `grading_retry` job, lock-guarded, every 60s |
| Benchmark | 18 human-labelled cases, harness, report, and a runner script |

---

## Verification

### Automated

```
backend  pytest                 361 passed  (was 242; +119)
backend  ruff check / format    All checks passed
backend  mypy core commons      Success: no issues found in 82 source files
```

New suites: `test_grading_prompts.py` (18), `test_grading_validation.py` (40),
`test_grading_service.py` (21), `test_attempts.py` (21), `test_grading_benchmark.py` (19).

### Against the live OpenRouter API

Verified with a real key and `inclusionai/ling-3.0-flash-fin:free`:

```
GOOD answer       score 95  strong        all 3 concepts hit
PARTIAL answer    score 65  developing    correctly identified the missing concept
WRONG answer      score 10  needs_work    correctly diagnosed the reversed signs
INJECTION         score 0   needs_work    "contains only instructions attempting to
                                           manipulate the grading process"
```

Zero invented concept keys, zero band disagreements across the four. The injection case is the
one that matters: a real model, given a real attempt to override its instructions, graded it as
an absent answer rather than following it.

### End to end over HTTP against the running stack

27 of 27 checks passed:

```
question served pre-submission     200, no ideal_answer, no rubric content
submit                             201, no score field, pre-grade status
resubmit                           200 not 201, original attempt, duplicate: true
poll until graded                  score in range, band, feedback all present
  ideal_answer revealed            matches the pinned version
  rubric still absent              no rubric / expected_concepts / common_mistakes
  concept keys                     subset of the rubric's declared keys
grade event                        1 row, validation_status "valid"
  provider / model / prompt_version / latency recorded
  rubric_version                   matches the version that graded
another user reading the grade     404
anonymous reading the grade        401
```

### Grading benchmark

Run against the live provider, before and after the fixes it surfaced:

```
                  before    after
cases graded      16/18     18/18
errors            2         0
agreement         75%       83%

after, by answer type:
  excellent                   100%
  good                        100%
  incorrect                   100%
  weak                        100%
  plausible_but_wrong         100%
  partial                      50%
  differently_phrased_correct    0%
```

No severe disagreements — every miss is one band, and all three are the grader being harsher than
the human label.

---

## Problems found and fixed

Three of these were found only by calling the real API. All the tests and the type checker were
green while every one of them was present.

1. **The configured model rejected the request outright.** `response_format`/`json_schema` is not
   supported by every model behind OpenRouter, and one that lacks it fails the whole call with a
   400 — `"model features structured outputs not support"`. The provider now detects that
   specific rejection, remembers it per model for the process, and retries without the
   constraint. Safe, because the schema was never what made a grade trustworthy: validation
   against the rubric is, and it runs identically either way.

2. **Dropping the schema dropped the field names with it.** The first fallback call returned
   valid JSON using `concepts` and `mistakes`, with no `band` and no `feedback`. Validation
   correctly rejected it, but the root cause was mine: the output contract lived *only* in the
   JSON schema, so nothing told the model what fields to emit once the schema was gone. The
   contract is now stated explicitly in the system prompt as well.

3. **`MAX_OUTPUT_TOKENS` was too tight.** Two benchmark cases came back with
   `finish_reason=length` and a truncated object. A truncated grade is a wasted paid call, not a
   saved one; raised 900 → 1600.

4. **JSON arrives wrapped.** Models routinely return a markdown fence or a sentence of preamble.
   Those responses are now unwrapped before parsing — but never *repaired*: malformed JSON still
   fails, because a grade nobody can trust is worse than no grade.

5. **A test really slept through the retry budget.** The provider-failure benchmark test took
   54.6 seconds, because 18 cases each exhausted the immediate-retry backoff with real
   `asyncio.sleep`. Patched to zero in the test: 57s → 2.7s for that file.

6. **Two things I wrote and then removed**: a `getattr(error, "call", None)` hack for an attribute
   that never existed, and a `rubric_version` read from a key inside the rubric JSON that nothing
   ever wrote. The second was a real correctness bug — grade events would have recorded rubric
   version `0` for every grade, making them unattributable, which is the entire point of the
   column. It now comes from the question version number.

7. **A test that asserted an impossible state.** I wrote a test that deleted a question version
   out from under an attempt; the foreign keys are `ON DELETE RESTRICT`, so it could not happen
   and the test was passing for the wrong reason. Replaced with one that drives the guard
   directly and says why the guard still earns its place.

---

## Design decisions

**Submission returns before grading runs.** The attempt is persisted, a background task grades it,
and the client polls. Grading inline would hold the request open for the length of a model call,
put the student's answer at the mercy of an HTTP timeout, and give the interface nothing to render
for ten seconds. No queue was added: a background task plus the scheduled sweep covers both the
fast path and the durability guarantee, and a broker would be infrastructure without a problem.

**Two retry mechanisms, on purpose.** They solve different problems. The immediate in-call retry
handles the common transient blip without making a student wait minutes. The scheduled sweep is
the durability guarantee — it survives a crash, a deploy, or a container restart between
persisting an answer and writing its grade. Only the sweep can lose nothing; only the immediate
retry is fast.

**The band is derived from the score.** The model is still asked for one, and disagreement is
recorded as a quality signal, but the persisted band comes from the question's own thresholds. A
score and a band that contradict each other cannot be resolved after the fact and would render as
an incoherent grade panel. This is a small, deliberate deviation from the PRD's conceptual schema,
which lists band as a model output; the field is still requested and still validated.

**Unknown concept keys are dropped, never coerced.** Keys are aggregated into mastery and grouped
in review. An invented key would fork a student's history into two unrelated concepts; a key
snapped to the nearest match would record a concept the student never demonstrated and move a
score that should not have moved. Dropping is the only safe option, and the drop is recorded.

**No keyword filtering on student answers.** Only control characters are stripped. Filtering for
"injection attempts" is an arms race that cannot be won, and it would mark down a student
correctly answering a question *about* prompt injection. The nonce fence and the validated output
schema are what actually contain the risk.

**The fake provider reads the rubric out of the prompt.** It could have been handed the concepts
directly, but then it would not exercise the same interface as a real provider, and a
prompt-construction bug that hid the concepts from a real model would pass every test.

**The benchmark is not a CI gate.** Real model calls cost money and are not deterministic; a
threshold asserted in CI would be flaky, expensive, and would fail for reasons unrelated to the
change under review. The tests verify the *harness*; quality is judged by running the benchmark
and comparing to the previous run.

---

## Honest scope statement

- **No grading UI.** This phase is backend only. There is no way for a student to reach the
  submission endpoint through the interface, because sessions are not created until the
  diagnostic in Phase 6. The flow is verified by tests and by HTTP, not by a browser.
- **Grading quality was measured against one free-tier model**,
  `inclusionai/ling-3.0-flash-fin:free`, not against the `openai/gpt-4o-mini` default in
  `.env.example`. The 83% figure is that model's, not the product's.
- **The grader runs harsh on two answer types.** Partial answers scored 50% agreement and the
  single differently-phrased-correct case scored 0% — all adjacent misses, all in the same
  direction. That is a real calibration finding for content review. I deliberately did not tune
  the prompt against 18 hand-labelled cases, because fitting a prompt to the benchmark would
  destroy the benchmark's value as a measurement.
- **The benchmark's 18 cases are labelled by me, not by a practitioner.** The labels are
  defensible but they are not expert consensus, and at least two of the disagreements above are
  arguable either way.
- **Cost is recorded as OpenRouter reports it**, in credits. A provider that does not report cost
  leaves the column null rather than storing a guess; there is no pricing table.
- **No free-tier grading limit.** `count_graded_since` exists and is unused. Entitlement gating is
  Phase 9.
- **No grade-flag endpoint.** Students cannot yet dispute a grade; `grade_flags` remains empty.
- **The retry sweep has not been observed recovering from a real crash.** It is covered by tests
  that drive it directly, not by killing a container mid-grade.

---

## Blockers

None.

---

## Next

**Phase 6 — Diagnostic.** The 24-question diagnostic: deterministic server-side composition,
session state, answer submission through the flow built here, results, category mastery, and the
recommended next action — with the polished assessment UX the product's credibility rests on.
Grading now exists to feed it.
