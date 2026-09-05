# Checkpoint — Phase 9: Billing

**Completed:** 2026-09-04
**Goal:** plans, Stripe Checkout, Stripe Customer Portal, webhook, entitlement lifecycle,
server-side gating and free-tier limits — tested through subscribe, cancel, resubscribe, refund,
expired Season Pass, duplicate webhook and delayed webhook.

---

## What was built

### Backend

| Area | Delivered |
|---|---|
| Plan catalogue | `core/services/billing/plans.py` — Free, Pro monthly, Season Pass; prices from configuration, never hard-coded |
| Provider boundary | `provider.py` (interface + normalised types), `stripe_provider.py` (the only module importing `stripe`) |
| Access decisions | `entitlement_service.py` — one place decides what a caller may do; gates read only what they need |
| Payment events | `webhook_service.py` — the only writer of entitlements, verified → recorded → applied |
| Repair | `reconciliation_service.py` + hourly `entitlement_reconciliation` job |
| Schema | `billing_events` table, `subscriptions.last_event_at`, one migration, up/down verified |
| Endpoints | `GET /v1/billing/plans`, `GET /v1/entitlements`, `POST /v1/billing/checkout`, `POST /v1/billing/portal`, `POST /v1/webhooks/stripe` |
| Gating | Practice start, answer submission and second-diagnostic composition, all 402 with structured detail |

### Frontend

`/pricing` (public, Season Pass emphasised), `/billing/success` (confirms access, never grants
it), a billing panel on `/account` covering all four plan states, `PaywallNotice`,
`AllowanceMeter` and `UpgradePrompt`, plus 402 handling in the practice start form, the practice
runner and the diagnostic start button.

---

## Verification

### Automated

```
backend  pytest                 530 passed  (was 475; +55)
backend  ruff / mypy            All checks passed / no issues in 101 source files
backend  alembic                up → down → up clean; `alembic check` finds no drift
web      vitest                 131 passed  (was 104; +27)
web      eslint / tsc / build   clean / clean / 22 routes
```

New suites: `tests/test_billing.py` (55) and `web/tests/Billing.test.tsx` (27).

Webhook tests post **real HMAC-signed payloads to the real endpoint**. Stubbing verification
would remove the only control standing between an anonymous POST and paid access, which is
precisely the thing worth testing.

### End to end over HTTP

22 of 22 checks passed against the running stack:

```
plans are public                        200, entitlement null when anonymous
billing reports itself unconfigured     paid plans marked not purchasable
entitlements / checkout anonymous       401
webhook with no signing secret          503, nothing written
new account                             free, all three capabilities true, allowance 3/3
checkout with no Stripe keys            503, not a stack trace
portal with no billing account          404
practice: start, answer, repeat         201, 201, 201, 402
  the refusal explains itself           reason, used 3, limit 3, upgrade_url /pricing
  entitlements agree with the refusal   can_start_practice false
diagnostic still allowed on free tier   200, answer accepted
  duplicate submit is not a paywall     200, duplicate true
  resuming is never refused             200, resumed true
```

### Browser

Walked `/pricing` anonymous and signed in, `/account` in the free, active and expired states, and
`/practice` with the allowance spent. The expired state was produced by moving a grant's
`active_until` into the past while leaving its status `active` — the page correctly showed "Your
access ended on August 26, 2026", proving expiry is decided by the clock rather than by the sweep
having run. The blocked practice page renders the paywall, disables both fieldsets and the submit
button, and still offers "See plans" — no dead end. All test data was removed afterwards.

### Not verified here

The webhook path has not been exercised through the containerised proxy: the running stack has no
`STRIPE_WEBHOOK_SECRET`, and picking one up needs a container restart, which this environment
cannot perform. It is covered end to end in the suite, against the real route, with real
signatures.

---

## Problems found and fixed

1. **The free practice allowance was unspendable.** The first rule counted practice sessions
   excluding abandoned ones — but starting a set abandons the previous one, so exactly one
   non-abandoned practice session ever exists and the count never passed 1. Every unit test
   passed, because they seeded sessions directly rather than going through the endpoint; the
   end-to-end walk caught it on the first run (`[201, 201, 201, 201]`). The allowance is now
   measured in **sets the student actually answered**, which is both unspoofable and the thing
   that costs money. A test now walks the real endpoint rather than seeding rows.

2. **A failed webhook could never be retried.** A handler failure was recorded as `failed` and
   re-raised so Stripe would retry — but the retry hit the duplicate path and returned 200 without
   running anything, stranding the event forever, because the provider only ever resends the same
   event ID. `claim` now hands back an event still in `received` or `failed` for reprocessing, and
   treats only `processed` and `ignored` as duplicates. A test drives a transient failure and its
   retry, and a second test proves three deliveries still grant exactly one Season Pass.

3. **A Stripe object is not a dict.** `construct_event` returns an `Event`, which raises on `.get`.
   Found by the first webhook test run. Converted once at the provider boundary with `.to_dict()`.

4. **The entitlement gates were doing six queries each.** `require_grading` runs on every answer a
   student submits. The gates now read the grant and, only if there is none, the one counter that
   matters — two queries, and the diagnostic path short-circuits before any of them.

---

## Design decisions

**A subscription and an entitlement stay separate records.** The subscription mirrors what Stripe
believes; the entitlement is what this application will honour. A cancelled subscription that is
still paid through the end of the month is exactly that difference. Merging them would force a
choice between billing the student honestly and giving them what they paid for, and would mean a
delayed or out-of-order webhook could grant or revoke access as a side effect of updating a
mirror.

**There is deliberately no fake payment provider**, despite the fake grading provider setting a
precedent. A fake grade is obviously local; fake paid access would be indistinguishable from
access that was bought, and the one rule this area cannot bend is that entitlements come only from
verified payment events. Local development uses Stripe test mode and `stripe listen`, which is
free and produces real, verifiable events.

**Idempotency is a database constraint, not handler logic.** The event is inserted before it is
acted on, and the insert decides whether this delivery processes it. A check-then-write would let
two simultaneous deliveries both pass the check. Most handlers are naturally idempotent anyway —
but a Season Pass is a one-time payment with no subscription to key on, so a replayed
`checkout.session.completed` would hand out a second pass, and no amount of careful handler code
fixes that as reliably as a unique constraint does.

**Ordering is decided by the provider's clock.** Stripe does not promise ordering, so
`subscriptions.last_event_at` stores the `created` timestamp of the last event applied and an
older event is skipped. Comparing local write times instead would compare two different clocks.
Without this a redelivered `updated` from before a cancellation restores paid access.

**Cancellation sets an end date rather than revoking.** `cancel_at_period_end` moves the grant's
`active_until` to the paid-through date; expiry then happens on its own, with no further event
required and no job that has to run.

**`past_due` does not revoke.** The card failed and Stripe is still retrying it. Locking a student
out mid-preparation over a decline that resolves itself in a day is a worse error than a day of
unpaid access.

**Expiry is evaluated against the clock on every read**, never against a stored status. A lapsed
Season Pass stops granting access the second it lapses, whether or not the reconciliation sweep
has run. The sweep marks rows expired for readability only.

**Reconciliation repairs but never grants.** It revokes access the provider says has ended, and
logs — rather than silently fixes — an active subscription with no grant, because that combination
means an event was lost and papering over it would hide that it happens at all.

**A full refund revokes; a partial one does not.** A partial refund is a support gesture, and
taking back a whole recruiting season over it turns a resolved complaint into a new one.

**The free tier is one diagnostic, N practice sets, and a rolling daily grading cap.** The
diagnostic is exempt from the grading cap: a 24-question sitting would exhaust any sane cap on its
own, and a half-graded diagnostic measures nothing — it is the free tier's entire argument. The
grading window is rolling rather than calendar, because a midnight reset hands two allowances to
anyone willing to wait for it and gives students in different timezones different products.

**The grading check sits after the duplicate check and before the insert.** A client retry of an
answer already stored is never refused, and a refusal never leaves a stored attempt that will
never be graded — which would look to the student like an answer that was swallowed.

**A 402 carries its reason and its numbers.** The interface can then say "you have used 3 of 3
practice sets" rather than "upgrade required". A student stopped mid-task is owed the reason
before the offer; a prompt that only sells reads as a trap.

**The paywall argument is made on the results page, not before.** `UpgradePrompt` names the
student's weakest category and counts their actual missed concepts, which is only possible once
the evidence is on the page. Generic pricing copy would say nothing they could not have read
before taking the diagnostic.

**The success page confirms access; it never grants it.** The browser has just come back from the
payment provider and knows the payment succeeded, and that knowledge is worth nothing — it polls
until the server agrees. Trusting the redirect would mean anyone who can type the URL has bought a
plan. A delayed webhook shows "Payment received. We are confirming your access", then a timeout
state that says the payment is safe rather than implying something is broken.

---

## Follow-ups for later phases

- Prices are configured as Stripe price IDs; the pricing page shows no amounts. Rendering real
  amounts means reading them from Stripe, which belongs with the Phase 11 pricing polish.
- Receipts are Stripe's for now. Phase 10 owns transactional email, including payment receipts.
- The landing page is still the Phase 1 placeholder with a pricing link added. The marketing
  landing page belongs to Phase 11.
