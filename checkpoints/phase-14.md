# Checkpoint — Phase 14: Final verification

**Completed:** 2026-09-05
**Goal:** verify the complete funnel end to end, run every check, re-run the security review, and
challenge the major assumptions — fixing all high-confidence issues before declaring completion.

---

## Outcome

**Three defects found, all fixed.** All three were in the free tier, all three were spending or
conversion controls that did not hold, and none of them was visible from reading the code — each
needed the product to actually be driven.

The funnel now passes 47 of 47 assertions end to end.

---

## The funnel

Landing → signup → onboarding → diagnostic → grading → results → paywall → practice → review →
progress → return, walked as a student walks it, asserting at every step.

**47 passed, 0 failed.** Including: consent defaults false and is separately grantable and
revocable; 24 questions across 8 categories, 3 each, difficulty ramping 1→4; no rubric in any
pre-submission payload; resume returns the same session; duplicate submit is idempotent; results
refused mid-sitting; all 24 graded; weaknesses and a recommendation produced; review carries no
answer text; detail carries full evidence and never the rubric; flagging is idempotent; all 8
categories measured and mastery agrees with results; history survives a new session; a second
diagnostic is refused; export works and carries no password hash.

---

## Defects found and fixed

### 1. The diagnostic consumed the allowance it is exempt from

A new account that did exactly what the product tells it to do — take the free diagnostic — ended
up with `graded_last_24h` of 24 against a limit of 15, `can_grade_answer` false, and
`can_start_practice` **true**. The interface would have offered practice and then refused every
answer with "you have used all 15 graded answers for today" to a student who had used none.

`require_grading` exempted diagnostic sessions from the check; the counter behind it still counted
diagnostic answers. The exemption was real and the accounting was not. Fixed by excluding
diagnostics from the counter, so the two agree.

This broke the product's core loop at "practice" on day one — the day a converted student is most
engaged — and fired the paywall with the wrong reason.

### 2. The allowance counted finished grades, not submitted answers

Grading is asynchronous, so an answer is dispatched to the provider long before it has a
`graded_at`. Counting only finished grades left that whole window uncounted. Fixed by counting
from submission: the spend is committed when the answer is accepted.

### 3. The limits were bypassable by concurrent submission

Twenty simultaneous answers were **all accepted and all graded** against a limit of fifteen —
every one a paid model call. Every free-tier limit was a check followed by a write in a separate
transaction, so concurrent requests all read the same pre-insert count and all passed.

Fixed with a short per-user Redis lock (`commons/locks.py`) holding the check and the insert
together. Per user, so students never contend; fails open on a Redis outage, matching the rate
limiter's documented posture. Verified: 20 concurrent submissions now yield exactly 15 accepted
and 5 refused.

**Also removed:** `SENTRY_DSN` from `.env.example`, which documented an observability integration
with zero references anywhere in the codebase.

---

## The grill-me pass

The assumption that broke was *"the free tier is enforced server-side."* It is enforced, and it
was still bypassable, because enforcement was a check-then-act and the counter measured the wrong
event. Three questions found all three defects: *what does the counter actually count?*, *what
happens between the check and the write?*, and *what does a real user's first day look like?*

`ALLOWED_ORIGINS` looked like a second phantom variable and was **not** — it is read by
`web/next.config.ts` for Server Actions. Verified before acting rather than removed on suspicion.

---

## Residual, deliberately not fixed

**The practice-set ceiling is enforced at the wrong point.** `require_practice` runs when a set is
*started*; `count_practice_sets_answered` counts sets that have been *answered*. A set started and
not answered costs nothing and counts nothing — which is deliberate and documented — so a client
that starts many sets before answering any can exceed three answered sets. A lock does not fix
this: it is a semantic gap, not a race. Daily spend stays bounded by the now-atomic grading cap,
so the exposure is slow accumulation rather than an unbounded burst. Closing it means deciding
where the set allowance belongs, which is a product decision about what a "used" set means, so it
is documented rather than chosen unilaterally. Detail in `docs/security-review.md` finding 5.

---

## Verification

| Check | Result |
|---|---|
| Full funnel | **47/47** assertions passing |
| Backend suite | **605 passing**, 0 failures (602 → 605: three free-tier regression tests added) |
| Frontend | typecheck, lint clean; 154 tests passing |
| `ruff check` / `ruff format` | clean, 155 files |
| `mypy core commons` | clean, 119 source files |
| Migrations | up → **downgrade to base** → up again, clean on a fresh database |
| Production build | `next build` succeeds; measured separately in Phase 13 at 23ms p50 for the landing page |
| Docker | all six services healthy — proxy 200, api 200, readiness reports postgres and redis healthy, scheduler heartbeat live with a 71s TTL |
| Environment config | every settings field and compose variable present in `.env.example`; one phantom entry removed |
| Security re-review | cross-account 404/401 on every object-scoped route; rubric protection holds; Phase 12 mid-diagnostic fixes still hold after the Phase 13 refactor touched the same method |
| New tests fail without their fixes | confirmed by reverting each |

**Not verified, and said so:** `docker compose build` could not be run — the Docker socket is not
reachable from this session. The running stack is the compose stack and every service is healthy,
which is strong evidence the images build and run, but it is not the same as a clean build.

---

## Open items carried forward

From `docs/security-review.md`: provision admins deliberately (no code path sets `is_admin`); add
`pip-audit`/`osv-scanner`/`gitleaks` to CI, since Python dependency advisories are checked by
nothing; the practice-set ceiling above; Redis `requirepass`; the `X-Forwarded-For` deployment
invariant if an ALB is ever put in front of Caddy.

From `docs/performance-review.md`: mastery reads a user's whole graded history; inline grading has
no concurrency cap; Redis has no `maxmemory`; container CPU and memory unmeasured.

None blocks launch.
