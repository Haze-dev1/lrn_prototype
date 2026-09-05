# Checkpoint — Phase 10: Email and analytics

**Completed:** 2026-09-04
**Goal:** diagnostic result email, receipts, weak-area nudge, analytics events, funnel tracking
and retention events — with sensitive answer text kept out of general analytics.

---

## What was built

### Backend

| Area | Delivered |
|---|---|
| Email boundary | `provider.py` interface, `resend_provider.py`, `log_provider.py` (default) |
| Messages | `templates.py` — results, receipt, weak-area nudge; HTML and text, escaped at interpolation |
| Orchestration | `email_service.py` — preference checks, delivery, send markers, two sweeps |
| Unsubscribe | `unsubscribe.py` — purpose-scoped HMAC tokens, no storage, no expiry |
| Analytics vocabulary | `events.py` — 18 named events, a public allowlist of 2, a property allowlist |
| Analytics dispatch | `service.py` — sanitises, dispatches without blocking, never raises |
| Retention | `retention_service.py` — week-2 and week-4 windows, deduped in Redis |
| Schema | 3 columns, 2 partial indexes, one migration, up/down verified |
| Endpoints | `GET`/`PUT /v1/account/email-preferences`, `POST /v1/emails/unsubscribe`, `POST /v1/analytics/events` |
| Jobs | `diagnostic_results_email` (2 min), `weekly_nudge_email` (Mon 09:00), `retention_events` (03:15) |

Twelve call sites instrumented across auth, sessions, attempts, grading, review, mastery and
billing — the full PRD funnel plus `grade_flagged`, `review_opened`, `mastery_improved` and
`paywall_reached`.

### Frontend

A public `/unsubscribe` page that acts on a click rather than on load, an email preferences
section on `/account` that saves each switch on its own, and `landing_view` recorded from the
landing page's server render — no analytics script reaches the browser.

---

## Verification

### Automated

```
backend  pytest                 585 passed  (was 530; +55)
backend  ruff / mypy            All checks passed / no issues in 118 source files
backend  alembic                up → down → up clean; `alembic check` finds no drift
web      vitest                 141 passed  (was 131; +10)
web      eslint / tsc / build   clean / clean / 23 routes
```

New suites: `tests/test_analytics.py` (20), `tests/test_email.py` (35),
`web/tests/EmailPreferences.test.tsx` (10).

### End to end over HTTP

16 of 16 checks passed against the running stack:

```
preferences without a session          401
landing_view from a browser            202 accepted
checkout_completed from a browser      202 ignored — cannot be forged
grade_received from a browser          202 ignored
invalid unsubscribe token              200, identical body to a valid one
study reminders default                on; marketing defaults off
signed-in toggle                       both directions, both preferences
unsubscribe with no session            200, preference actually written
  marketing left untouched             confirmed
  the same link cannot re-subscribe    confirmed
```

### Browser

Opened a real minted unsubscribe link: the page asked before acting, the click turned reminders
off, and `/account` then showed the switch off — the emailed link, the API and the account page
all agreeing. Toggling it back on restored the row, verified in the database. All test data was
removed afterwards.

### Rendered messages

All three were rendered and read. The results email leads with the number, the nudge names one
category and one action, and the receipt confirms access without inventing an amount.

---

## Problems found and fixed

1. **An unsubscribe token signed with the wrong secret looked like a broken endpoint.** The first
   end-to-end run failed two checks: the token was minted by a local script using a different
   `JWT_SECRET` than the container, so the endpoint correctly rejected it — and, by design, still
   answered 200. That is the intended behaviour (a public endpoint that distinguishes a valid
   token from an invalid one is a way to test whether an address is registered), but it makes a
   misconfiguration look like a bug. Recorded as a pitfall in `CLAUDE.md`.

2. **The first free-tier-style allowlist would have leaked through nesting.** `sanitise` initially
   only checked key names. A dict or list value under a permitted key would have carried whatever
   was inside it. Non-scalars are now dropped outright, with a test that tries exactly that.

3. **Module-level `pytest.mark.asyncio` warned on every synchronous test.** `asyncio_mode = "auto"`
   already handles async tests; the explicit mark only produced noise. Removed.

---

## Design decisions

**No delivery table.** Three columns instead: `sessions.results_email_sent_at`,
`profiles.last_nudge_email_at`, and the existing `billing_events` idempotency for receipts. Each
fact lives on the row it is about, and a sweep that sets the marker only on success gives the same
exactly-once guarantee a delivery log would — with no second table to keep in step, and retries
for free. A generic table would have been a mechanism used in exactly three places, each of which
already had a natural home for the fact.

**Results are mailed by a sweep, not at completion.** Grading is asynchronous, so when a student
submits their last answer none of it may be graded. Driving from stored state rather than an event
also means a crash, a deploy or a provider outage between finishing and sending costs a delay
rather than the email.

**A wholly ungradeable diagnostic is still mailed, and says so.** There is nothing left to wait
for, and silence would leave the student expecting mail that will never come. The alternative —
reporting a score from the fraction that graded — is a wrong number, not an early one.

**Study reminders default on; marketing defaults off.** They are different things. A reminder that
something is due is the product working; a spaced-repetition tool that never says so has stopped
being one. Marketing is something sold, and stays opt-in. The on-by-default is only defensible
because every message carries a one-click unsubscribe that needs no sign-in.

**Unsubscribe is a signed token, stored nowhere.** Verifiable from the secret alone, so there is no
table to grow and no lookup on a public endpoint. Deliberately no expiry: a link in a six-month-old
email must still work, and someone who forges one can only *stop* mail to an address they cannot
read. The purpose is inside the signature, so a reminders token cannot be replayed against another
preference.

**An emailed link can only turn mail off.** The endpoint writes `False` rather than taking a value
from the caller. Re-subscribing requires signing in — the correct asymmetry, since stopping
unwanted mail should be as easy as possible and starting it should not.

**The unsubscribe page acts on a click, not on load.** Mail scanners, link previewers and corporate
security proxies fetch every URL in a message on arrival. A GET-triggered unsubscribe would
unsubscribe people who never opened the email.

**A skipped nudge does not mark the student.** Someone with nothing worth saying this week stays
eligible for next week; marking them would push them a further interval back every time, forever.

**Two allowlists, not a blocklist.** Event names are fixed so a funnel does not break the day
someone writes `diagnostic_complete`. Properties are fixed because a blocklist has to anticipate
every name someone might give an answer field and only has to be wrong once. A length cap is the
backstop underneath both: an answer is never 120 characters.

**A browser may assert exactly two events.** `landing_view` and `paywall_reached` genuinely only
happen in a browser. Everything else is recorded server-side, where the event is a consequence of
work the API actually did — an event a client can assert is an event a client can fabricate, and
`checkout_completed` from an anonymous POST would corrupt the number the product is measured on.
The endpoint takes no properties at all, because a property bag from an untrusted client is a
free-text channel straight into the analytics store.

**`landing_view` is recorded from the server render.** No analytics script reaches the browser, so
nothing is blocked by an ad blocker, nothing costs the reader a request, and there is no
third-party bundle on the product's most-visited public page.

**Analytics can never fail a request.** `track` dispatches onto the loop and returns; providers
swallow their own failures; a strong reference set stops in-flight sends being garbage collected
under load. Scheduled jobs use the awaited form, because they have no request to hold open.

**Retention is a sweep, deduped in Redis.** A return window is entered, and no single request knows
it is the first of one. A lost dedupe key costs one duplicated point on a chart and nothing else,
which is exactly the kind of state Redis is for here — and it double-counts rather than
under-counts on failure, which is the right way round for a metric where a missing return looks
like churn.

---

## Follow-ups for later phases

- The email templates are dark-on-light and deliberately plain. A visual pass belongs with the
  Phase 11 design work, alongside the marketing landing page.
- `EMAIL_PROVIDER=resend` has not been exercised against Resend's live API — there is no account
  configured in this environment. The adapter is a single documented POST, and the path above it is
  covered end to end with a recording provider.
- Analytics dashboards and the metric definitions in PRD §46 are a reporting concern, not an
  application one; the events they need are now all emitted.
