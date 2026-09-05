# Checkpoint — Phase 12: Security gate

**Completed:** 2026-09-05
**Goal:** an explicit security review across the full checklist, a genuine attempt to break the
product logically, and documented findings and fixes.

Full report: `docs/security-review.md`. This checkpoint records what was done and what changed.

---

## Verdict

**PROCEED WITH NOTES.** Three findings, three fixed. No cross-account access path exists anywhere
in the API, and nothing found was a remote-unauthenticated compromise.

---

## Method

Scanners first, then data-flow reasoning, then live probes against the running stack. The probes
are the part that mattered: two of the three findings were invisible from reading the code,
because the code looked correct at every individual endpoint and the rule they broke spanned
several.

Seven authenticated accounts were driven through the real API — registration, diagnostic
composition, answer submission, grading, completion, results, review, progress, flagging, export
and deletion — with a second account attempting every object-scoped route against the first's
objects, and an anonymous client attempting the same.

Scanners: `bandit` (15,728 LOC, 0 high, all findings triaged as false positives), `npm audit`
(0 vulnerabilities), `mypy` and `ruff` clean. **`gitleaks`, `trufflehog`, `semgrep`,
`osv-scanner` and `pip-audit` were absent** — reported by name in the review rather than passed
over, since Python dependency advisories were checked by no tool at all.

---

## Findings and fixes

### 1. HIGH — diagnostic grades and reference answers readable mid-sitting

The one that matters. `GET /v1/attempts/{id}` returned `score`, `band`, `feedback`,
`concepts_missed` and `ideal_answer` for an attempt in a diagnostic that was still in progress,
and `GET /v1/review` listed the same scores. The results endpoint already answered 409 and the
interface never asks — the diagnostic runner does not poll, only the practice runner does — so
the rule existed in the client and in one endpoint out of three.

The diagnostic response hands the client an `attempt_id` for every question, so nothing had to be
guessed. A student polling between questions would learn their running score and read the
reference answer for material still being assessed, which corrupts the diagnostic and every
mastery score, trend and recommendation derived from it.

Fixed in two places, scoped so practice is untouched:

- `AttemptController.get` loads the parent session and returns state only for an unfinished
  diagnostic — placed after the ungraded early return, so polling a still-grading answer costs no
  extra query.
- `CRUDAttempt.list_for_user` gained `exclude_unfinished_diagnostic`, set by review. A parameter
  rather than an unconditional filter, because the same query backs the **data export**, which
  must return everything the account holds.

### 2. MEDIUM — a deployed environment could boot on a repository-published credential

`JWT_SECRET: Field(min_length=32)` proves a value was supplied, not chosen, and the placeholder in
`.env.example` is 60 characters. Copying that file and deploying — the documented setup step —
signs every access token with a key anyone who has read the repository knows. Complete
authentication bypass, including admin, from one very ordinary omission.

Fixed with a `model_validator` that refuses to construct settings in `production` or `staging`
when `JWT_SECRET` or `DATABASE_URL` still carries a published placeholder. Local environments are
exempt. Refusing to boot is the only failure mode an operator cannot skip past.

### 3. LOW — twelve admin endpoints have no provisioning path

`is_admin` defaults false and **no code anywhere writes it**. The good half: no privilege
escalation path exists, at all. The bad half: the entire admin surface is unreachable in every
deployment, so the first admin gets made by hand-written UPDATE against production.

**Not fixed** — it needs a product decision on how admin should be granted. Recommended a
`scripts/grant_admin.py`. Documented rather than chosen unilaterally.

---

## What was verified sound

Tested, not assumed. Cross-account access on every object-scoped route (404 to a non-owner, 401
to anonymous, including with fully valid bodies so the check is not merely behind schema
validation). Question protection — no rubric field in any pre-submission payload, and a question
outside your own session's composition is 404 even when the session is yours. Admin routes 404 to
an ordinary user. Stripe webhook signature verification, fail-closed 503 when unconfigured,
constraint-based idempotency and out-of-order rejection. Entitlements writable only by the
webhook. Analytics allowlist — `checkout_completed` and `user_signed_up` asserted from a browser
were both `ignored`, and smuggled answer text and email were dropped. Refresh-token theft
detection — **replaying a rotated token revokes the whole family**, reproduced. Argon2id,
enumeration closed on both sign-in and registration. Data export and deletion. Prompt-injection
fencing. SQLAlchemy everywhere, no interpolation, no `pickle`/`eval`/`subprocess`. No XSS sink in
the frontend. Container posture — production publishes only the proxy, both images non-root,
confirmed from the host that 8000 and 3000 are closed.

The control I most expected to fail did not: `client_identifier` reads the leftmost
`X-Forwarded-For`, the classic bypass, but three forged `X-Forwarded-For` / `X-Real-IP` /
`Forwarded` values collapsed into one Redis bucket keyed on the real peer. Caddy overwrites them.

---

## Verification

| Check | Result |
|---|---|
| Backend suite | **597 passing, 0 failures** — 12 tests added this phase (3 attempt, 3 review, 6 configuration) |
| Frontend | typecheck, lint clean; 154 tests passing |
| `ruff check` / `ruff format` | clean |
| `mypy core commons` | clean, 118 files |
| New tests fail without the fixes | confirmed — reverted each fix, 5 targeted failures, restored |
| Full diagnostic funnel after the fixes | 24/24 submitted, graded and completed; results carry categories, weaknesses and an explained recommendation; review 20 items; 8/8 categories measured; `ideal_answer` restored after completion |

A note on process: an early full-suite run reported 26 failures. That was my own artifact — two
pytest runs overlapping on the same `lrn_test` database and Redis DB. A single clean run was
green. The failures were not real and nothing was "fixed" to make them go away.

---

## Open items

None blocking. In order: provision admins deliberately (finding 3); add `pip-audit`/`osv-scanner`
and `gitleaks` to CI, since Python dependency advisories are currently checked by nothing; put
`requirepass` on Redis when a coordinated `REDIS_URL` change is convenient; treat "the edge
overwrites `X-Forwarded-For`" as a deployment invariant and re-run that probe if an ALB is ever
put in front of Caddy; consider a breached-password check. Detail and reasoning for each in
`docs/security-review.md`.

---

## Documentation updated

- `docs/security-review.md` — new, the full report.
- `CLAUDE.md` — the diagnostic invariant now states that the API enforces it and names all three
  endpoints; the review section records `exclude_unfinished_diagnostic` and why the export does
  not set it; two pitfalls added; the security review linked from the header.
