# Checkpoint — Phase 4: Question bank + admin

**Completed:** 2026-09-04
**Goal:** question and version APIs, rubric completeness validation, admin question management,
activation and retirement, version history — and tests proving ideal answers and rubrics never
reach a client before submission.

---

## What was built

### Backend

| Area | Delivered |
|---|---|
| Student question access | `GET /v1/categories`; `GET /v1/sessions/{id}/questions/{qid}` — the only path to a question |
| Rubric validation | `RubricValidator` — blocking errors separated from quality warnings, every failure reported at once |
| Admin question management | List with filters and keyset pagination, detail with history, create, taxonomy edit |
| Lifecycle | Activate / retire, with activation refused when no version is published |
| Versions | Create, publish (superseding the previous), edit a draft in place, read full content, validate |
| Coverage | Per-category gradeable counts and diagnostic readiness |
| Content | 40 authored questions, five in each of the eight categories, at difficulty 1-4 |
| Seeder | Idempotent by `source_key` and content hash; validates everything before writing anything |
| Schema | `questions.source_key`, nullable and unique |

### Frontend

Admin surface at `/admin/questions` — coverage panel, URL-backed filters, question table, create
form, and a detail page combining the version editor, lifecycle control, version history and
taxonomy form. `Textarea` primitive, `requireAdmin` route guard, and a typed admin API client.

---

## Verification

### Automated

```
backend  pytest                 242 passed  (was 143; +99)
backend  ruff check / format    All checks passed / 92 files formatted
backend  mypy core commons      Success: no issues found in 71 source files
web      vitest                 30 passed   (was 9; +21)
web      eslint / tsc           clean / clean
web      next build             Compiled successfully, 11 routes
```

New backend suites: `test_questions.py` (16), `test_admin_questions.py` (50),
`test_rubric_validation.py` (16), `test_question_seed.py` (17).

### End to end, over HTTP against the running stack

A 38-check script drove the real API through the proxy. All 38 passed:

```
student -> every admin route        404, body "Not found"  (not 403)
anonymous -> admin route            401
anonymous -> /v1/categories         200, eight categories
coverage after seed                 diagnostic_ready true, 40 selectable
admin list                          paginates, returns a cursor
admin list body                     contains no "ideal_answer"
create question                     201, always draft
activate with no rubric             409
publish incomplete rubric           422, >= 2 specific errors
  ... and left no stray draft       version_count 0
save incomplete content as draft    201
validation endpoint                 reports publishable, changes nothing
edit draft in place                 200
publish complete rubric             200
edit published version              409
activate with rubric                200
publish v2                          201, numbered 2
  -> exactly one published          1
  -> v1 became superseded           1
  -> history preserved              2 versions
republish superseded                409
retire                              200, versions preserved
version via wrong question ID       404
unknown category filter             400
```

### Seeder, against the real development database

```
first run    40 entries: 40 created, 0 updated, 0 unchanged, 40 activated
second run   40 entries: 0 created, 0 updated, 40 unchanged, 0 activated
dry run      40 entries: nothing written
```

### Browser

Signed in as an administrator and drove the list, detail, version and create pages. Coverage
reports ready with 40 gradeable, the published version renders read-only with its explanation,
and the console carries no application errors or hydration warnings. Signed in as an ordinary
student, all three admin pages return **404** with zero admin content in the response body.

---

## Problems found and fixed

1. **The version editor showed the wrong content on client-side navigation.** Switching between
   versions rendered an empty form, while a hard reload was correct. The editor seeds its state
   in a `useState` initialiser, which does not re-run when only props change, so React reused the
   component and kept stale state. Fixed by keying the editor on the version ID. Only the browser
   pass found this — every test and the production build were green with the bug present. The
   regression test was confirmed to fail without the key.

2. **The admin page title leaked through the 404.** A student requesting `/admin/questions` got a
   404 page whose streamed RSC payload still contained `"Question bank · LRN"`, because a static
   `metadata` export is rendered before the component calls `notFound()`. That confirms the route
   exists and names it — exactly what the API's 404-instead-of-403 answer avoids saying. Moved to
   `generateMetadata` behind the same admin gate, and memoised the identity fetch with React
   `cache` so gating twice costs one request. Re-verified: zero admin terms in the response.

3. **The test suite's result depended on the developer's `.env`.** `make test-api` sources `.env`
   for the database credentials, which also exports `GOOGLE_CLIENT_ID`. With Google sign-in
   configured locally, the endpoint stopped being "unconfigured" and a Phase 3 test failed —
   nothing to do with the code under test. `conftest.py` now clears the integration credentials
   outright. Verified by running the full suite with a real client ID exported: 242 pass.

4. **`python scripts/seed_questions.py` could not import `core`.** Running a script by path puts
   `scripts/` on `sys.path` instead of the application root. `make seed` uses
   `python -m scripts.seed_questions`; the script's own usage docstring was corrected after being
   proved wrong.

5. **The coverage route would have been parsed as a question ID.** `/questions/coverage` is
   declared above `/questions/{question_id}` so the literal path matches first.

6. **A documentation claim was wrong before it shipped.** The draft said the bank spans difficulty
   1-5; counting the content showed 1-4. Corrected, and the gap is stated explicitly rather than
   quietly rounded off.

---

## Design decisions

**Drafts are editable in place; published and superseded versions are frozen.** The invariant that
matters is that a version which has graded an attempt is immutable — and a draft never can be one,
because sessions are composed exclusively from published versions. Freezing drafts as well would
force an author to burn a version number on every typo and bury real rubric history under editing
noise. The API returns 409 with an explanation, and the interface renders a frozen version
read-only rather than offering a form that would fail on submit.

**Two response types, not one type with optional fields.** `QuestionForAnsweringResponse` has
nowhere to put an ideal answer, so a future change that tried to include one produces a validation
error rather than a silent leak. The admin types are separate again, and the list and history
shapes carry no content at all, so rubrics stay out of the responses fetched most often.

**The admin dependency is on the router, not the routes.** An endpoint added below cannot be left
unprotected by forgetting a decorator. The authorization test is parameterised over all eleven
routes for the same reason.

**Validation runs before the insert.** A rejected publish leaves no stray draft to clean up.

**Seeding compares a content hash, not fields.** Sorted-key canonical JSON means reordering the
content file is not an edit, so reformatting cannot churn every question's version history.

**A stable `source_key` rather than seeding only into an empty table.** Primary keys are generated
by the database, so authored content needs its own handle to be updated rather than duplicated.

---

## Honest scope statement

- **No question is authored at difficulty 5.** The schema and API allow it; the bank runs 1-4.
  A selection rule that requires a level-5 question will find none.
- **There is no self-service route to become an administrator.** `is_admin` is set directly in the
  database. Admin user management is not built.
- **No grade-flag surface.** `grade_flags` still exports as an empty list; the flag API and its
  admin review workflow are Phase 9-adjacent work, not built here.
- **The rubric is edited as raw JSON** in the admin interface. It is validated for shape and for
  band-threshold ordering, but there is no structured editor for it.
- **Draft versions cannot be deleted.** An abandoned draft stays in the history.
- **The list search runs `ILIKE` against prompts** with no index behind it. Fine at 40 questions;
  it will need a trigram index or full-text search well before the bank reaches thousands.
- **No E2E suite.** Playwright is still unconfigured. The end-to-end evidence above is a script
  and a manual browser pass, not an automated regression gate.
- **The 40 questions have not been reviewed by a domain expert.** They are written to be
  technically correct and to grade well, but no practitioner has signed off on the content.

---

## Blockers

None.

---

## Next

**Phase 5 — OpenRouter grading.** Provider abstraction, the OpenRouter provider, structured schema
validation, retries and timeouts, the attempt state machine, grade audit events, prompt-injection
defences, and cost and latency logging — then benchmark fixtures to validate grading behaviour.
The question bank now exists to grade against.
