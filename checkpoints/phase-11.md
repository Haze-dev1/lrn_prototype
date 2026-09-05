# Checkpoint — Phase 11: Polish and UX quality pass

**Completed:** 2026-09-04
**Goal:** a complete visual and UX pass — spacing, typography, responsive behaviour, keyboard
navigation, loading, error and empty states, transitions, copy, the mobile diagnostic and the
desktop practice and review surfaces — plus the marketing landing page the product had never had.

This phase added no product capability. Everything below is either a defect found by walking the
running application, or the landing page, which was still the Phase 1 placeholder.

---

## The audit

Walked every signed-in surface in a real browser at desktop width, then again at 390px, and read
the console on each. The window manager here refuses resize requests and the app sends
`X-Frame-Options: DENY`, so mobile was reproduced by stripping the responsive class variants —
which is exactly what a sub-768px viewport renders, since those classes are the only difference.

Six defects found, all in surfaces that already "worked":

| # | Defect | Where |
|---|---|---|
| 1 | The landing page was still the Phase 1 placeholder — "FOUNDATION · PHASE 1", a service-status debug panel, and two CTAs that were buttons wired to nothing | `/` |
| 2 | The mobile nav overflowed: seven destinations in a non-wrapping row made the whole page scroll horizontally (`scrollWidth` 1881 at a 390px viewport) | `AppShell` |
| 3 | No sign-out on mobile at all — identity and the control both sat in a `hidden md:block` sidebar footer | `AppShell` |
| 4 | The paywall meter rendered **"53 of 15 used"** on a real account | `PaywallNotice` |
| 5 | A session was a dead end: the runners render without the shell, so the only way out of a 24-question sitting was the browser's back button | diagnostic and practice runners |
| 6 | Filter toggles were ghost buttons beside two bordered selects, so they read as captions rather than controls | `ReviewFilters` |

And three route-level states that did not exist at all: `not-found.tsx`, `error.tsx`, and any
loading boundary. A bad link rendered Next's unstyled black 404 with nothing to click; an
unhandled server error would have rendered "Application error: a server-side exception has
occurred", which the project's own standards forbid.

---

## What was built

### The landing page

A full rebuild against PRD §17: problem, product loop, an example graded answer, mastery
visualisation, adaptive practice, pricing and a close.

**The signature is a marked-up graded answer.** Every product in this category can write
"AI-powered feedback"; almost none can show the artifact. So the first thing under the headline is
a real question, a plausible two-thirds answer, the two concepts it established underlined in the
student's own words, and the two it missed hung off it as a marker's note. The score arrives a
beat later, in the order a student actually experiences it.

That reveal is a CSS keyframe, not a component — the page ships **zero client JavaScript**, and
the effect costs the reader nothing. It is a single short reveal of an already-computed result,
not a simulated "thinking" animation, which §19 rules out and the product does not have.

**Typography carries a rule rather than a new font.** No display face was added: the app already
has an identity, and a serif on the marketing page only would make the landing feel like a
different product. The deliberate choice is semantic — **mono is the grader's voice, sans is the
student's**. Every piece of machine judgement on the page (scores, bands, concept keys, category
labels, difficulty) is mono; every piece of human prose is sans. Applied without exception.

**Colour stays scarce.** The band colours are the only saturated hues on the page and they appear
only where they carry a grade. No gradient blob, no glass, no floating assistant.

### Fixes

- Mobile nav scrolls horizontally instead of wrapping, and carries identity and sign-out.
- Both meters clamp: usage can legitimately exceed an allowance, and "53 of 15" reads as broken
  arithmetic rather than as a limit.
- `SessionExit` — one muted link out of a running session, with copy that says whether it resumes.
- `FilterToggle` — bordered in both states, filled when active.
- `not-found.tsx`, `error.tsx`, a shared `PageSkeleton`, and `loading.tsx` on the four pages that
  wait on the most data.

---

## Verification

```
web      vitest                 154 passed  (was 141; +13)
web      eslint / tsc / build   clean / clean / 23 routes
backend  pytest                 585 passed, unchanged
backend  ruff / mypy            All checks passed / no issues in 118 source files
```

New suite: `web/tests/Polish.test.tsx` (13) — every test is a regression for a defect above, not a
feature. The 404 offers two ways out, the error boundary never renders the exception message, the
meters clamp, the session exit promises resumption only where resumption happens, and the landing
page renders an unmeasured category as unmeasured rather than as a zero.

### Browser

Re-walked the landing page at 1440px and 390px, the dashboard and review at both, the practice
runner mid-question, and a deliberately broken URL. Tabbed into the hero and confirmed the focus
ring is the accent colour and clearly visible against the light primary button.

---

## Problems found and fixed during the work itself

1. **The missed concepts broke the sentence.** The first version dropped them inline where they
   belonged — "That gets you to equity value [minority interest] [preferred stock]" — which was the
   intended gap but read as corrupted text: a reader repairs the grammar before they notice the
   point. Moved to a hung margin note, which is what a marker actually does.

2. **The card said everything twice.** It carried a "concepts hit / concepts missed" list under
   mark-up that already named both sets in the student's own words. Cut the list; the annotation
   is stronger alone.

3. **The loop did not close.** The heading said "five steps, and then the first one again" over a
   layout that stopped at 05. The last card now numbers itself `05 → 01`, so the claim and the
   drawing agree.

4. **I reported a focus-ring bug that was not one.** A first computed-style read returned the
   button's text colour; a second read and the screenshot both showed the accent ring rendering
   correctly. Verified before acting rather than "fixing" working code.

5. **A hydration error in the console was mine.** The class-stripping used to simulate mobile
   removes classes React expects, so it warns. Recognised as the tool rather than the product, and
   confirmed the app's own pages log nothing.

---

## Design decisions

**The hero is a demonstration, not a claim.** A student deciding whether to spend forty minutes on
a diagnostic wants evidence that the grading is worth having. The marked answer is that evidence,
and it does the work of three paragraphs of copy.

**Absence is drawn, not described.** The one piece of visual invention on the page is the dashed
outline for a concept the grader looked for and did not find. A strikethrough would say something
different — nothing was crossed out, something is missing — and the distinction is the product's
whole thesis.

**The loop is numbered because it is genuinely a sequence.** Numbered markers are a template
default and were tested against that: the order carries information the reader needs, and the
return from the fifth step to the first is the product's actual argument, so the numbering closes.

**The mobile nav scrolls rather than wraps.** A wrapping row pushes the page's content below the
fold before the reader has done anything. Horizontal overflow inside the nav keeps every
destination one tap away and costs no vertical space.

**A session keeps its exit but not its navigation.** "No distractions" and "no way out" are
different things. One muted link, and copy that says a diagnostic resumes exactly where it was
left — which is the fact that makes leaving safe rather than costly.

**The error boundary never renders `error.message`.** It can carry a query, a path, or an upstream
provider's wording. The digest is shown instead: Next writes the same hash to the server log, so a
student can quote it and someone can find the real error without it ever being displayed.

**Loading is a shape, not a spinner.** The skeleton reserves the layout the real page will occupy
so content does not jump when it arrives.

---

## Follow-ups for later phases

- The email templates are still deliberately plain. They render correctly and carry no rubric
  content; a visual pass on them was out of scope here and is not blocking.
- The pricing page shows no amounts, because prices live in Stripe as price IDs. Rendering real
  figures means reading them from the provider — noted in Phase 9 and still open.
