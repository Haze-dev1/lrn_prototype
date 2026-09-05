"""Processing of verified payment events — the only thing that writes an entitlement.

Nothing else in the application grants paid access. Not the checkout endpoint, which only creates
a link; not the success page, which the browser controls and which a student can reach by typing
the URL; not a support script. Access appears when a signed event from the provider says money
moved, and at no other moment.

Three properties matter here, in this order:

**Verified.** The signature is checked before the payload is looked at. An unverified body is an
anonymous POST claiming a payment.

**Idempotent.** Stripe delivers at least once and retries anything that is not a 2xx. The event
is inserted first and the insert is what decides whether this delivery processes it, so a
duplicate loses at the unique constraint rather than at a check the next duplicate would also
pass. An event whose handler *failed* is deliberately reprocessed rather than treated as a
duplicate — the provider is retrying it because the last attempt returned a 5xx, and refusing the
retry would strand it forever.

**Ordered.** Stripe does not promise ordering. Every subscription write compares the provider's
own clock against the last event applied, so a redelivered `updated` from before a cancellation
cannot restore access that was taken away.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from core import logger
from core.constants.enums import (
    BillingEventStatus,
    Entitlement,
    EntitlementStatus,
    Plan,
    SubscriptionStatus,
)
from core.cruds.billing_crud import CRUDBillingEvent, CRUDEntitlement, CRUDSubscription
from core.cruds.user_crud import CRUDUser
from core.services.analytics.events import AnalyticsEvent
from core.services.analytics.service import analytics
from core.services.billing.plans import PRO_MONTHLY_PLAN, get_plan
from core.services.billing.provider import (
    PaymentProvider,
    ProviderEvent,
    ProviderSubscription,
    get_payment_provider,
)
from core.services.billing.stripe_provider import StripeProvider
from core.services.email.email_service import EmailService

logging = logger(__name__)

# Statuses that grant access. `past_due` deliberately does not revoke: the card failed, the
# provider is still retrying it, and locking a student out mid-preparation over a bank decline
# that resolves itself in a day is a worse error than a day of unpaid access. Access ends when
# the subscription actually terminates.
_GRANTING_STATUSES = {SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING}
_GRACE_STATUSES = {SubscriptionStatus.PAST_DUE}

#: Event types this application acts on. Everything else is recorded and ignored, so the log
#: still shows what arrived without the handler pretending to understand it.
HANDLED_EVENTS = frozenset(
    {
        "checkout.session.completed",
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
        "charge.refunded",
    }
)


class BillingWebhookService:
    """Verifies, records and applies payment provider events."""

    def __init__(self, provider: PaymentProvider | None = None) -> None:
        """
        Initialise the service with a payment provider and the CRUD layers it writes through.

        Args:
            provider: Payment provider to use; defaults to the configured one.
        """
        self.provider = provider or get_payment_provider()
        self.CRUDBillingEvent = CRUDBillingEvent()
        self.CRUDSubscription = CRUDSubscription()
        self.CRUDEntitlement = CRUDEntitlement()
        self.CRUDUser = CRUDUser()
        self.EmailService = EmailService()

    async def handle(self, *, payload: bytes, signature: str | None) -> dict[str, Any]:
        """
        Verify one webhook delivery and apply it exactly once.

        A handler failure is recorded and re-raised so the route can answer with a 5xx and the
        provider retries. Swallowing it would return 200 to a delivery that changed nothing, and
        the provider would never send it again — losing a payment silently, which is the one
        outcome this system must not produce.

        Args:
            payload: Exact request body as received.
            signature: The provider's signature header.

        Returns:
            dict[str, Any]: What was done, for the route to log and the provider to ignore.

        Raises:
            SignatureVerificationFailed: The payload is not authentic.
            PaymentConfigurationError: No signing secret is configured.
            Exception: The handler failed and the delivery should be retried.
        """
        logging.info("Executing BillingWebhookService.handle")
        event = self.provider.verify_event(payload=payload, signature=signature)

        record, should_process = await self.CRUDBillingEvent.claim(
            provider=self.provider.name,
            provider_event_id=event.event_id,
            event_type=event.event_type,
            occurred_at=event.created_at,
            summary=self._summarise(event),
        )
        if not should_process:
            # A redelivery of an event that already reached a terminal state. Answering 200
            # without re-running the handler is the whole point of claiming first. An event that
            # *failed* is not this case — the provider is retrying it precisely because the last
            # attempt returned a 5xx, and `claim` hands it back for another go.
            logging.info(f"Ignoring duplicate delivery of billing event {event.event_id}")
            return {"status": "duplicate", "event_type": event.event_type}

        if event.event_type not in HANDLED_EVENTS:
            await self.CRUDBillingEvent.finish(
                event_id=record.id, status=BillingEventStatus.IGNORED
            )
            return {"status": "ignored", "event_type": event.event_type}

        try:
            outcome = await self._apply(event=event)
        except Exception as error:
            logging.error(f"Error in BillingWebhookService.handle: {error}")
            await self.CRUDBillingEvent.finish(
                event_id=record.id, status=BillingEventStatus.FAILED, error=str(error)[:500]
            )
            raise

        await self.CRUDBillingEvent.finish(event_id=record.id, status=BillingEventStatus.PROCESSED)
        return {"status": "processed", "event_type": event.event_type, **outcome}

    @staticmethod
    def _summarise(event: ProviderEvent) -> dict[str, Any]:
        """
        Reduce a provider event to the identifiers worth storing.

        Never the raw payload. A Stripe event carries the customer's name, email address and card
        metadata, none of which this database needs to reconcile a payment, and all of which would
        become one more copy of personal data to export, delete and defend.

        Args:
            event: The verified event.

        Returns:
            dict[str, Any]: Identifiers only.
        """
        payload = event.payload
        summary = {
            "object_id": payload.get("id"),
            "customer_id": payload.get("customer")
            if isinstance(payload.get("customer"), str)
            else None,
            "user_id": (payload.get("metadata") or {}).get("user_id"),
            "plan": (payload.get("metadata") or {}).get("plan"),
        }
        return {key: value for key, value in summary.items() if value is not None}

    async def _apply(self, *, event: ProviderEvent) -> dict[str, Any]:
        """
        Route one verified event to its handler.

        Args:
            event: The verified event.

        Returns:
            dict[str, Any]: Handler outcome for the audit log.
        """
        if event.event_type == "checkout.session.completed":
            return await self._on_checkout_completed(event=event)
        if event.event_type.startswith("customer.subscription."):
            return await self._on_subscription_event(event=event)
        if event.event_type == "charge.refunded":
            return await self._on_charge_refunded(event=event)
        return {}

    async def _resolve_user_id(self, payload: dict[str, Any]) -> uuid.UUID | None:
        """
        Find which user an event belongs to.

        Metadata first, because it is set by this application at checkout and travels with the
        subscription for its whole life. The customer ID is the fallback for events that predate a
        metadata change or are produced by the Customer Portal, where this application sets
        nothing. An event that resolves to neither is recorded and dropped rather than guessed at
        — granting access to the wrong account is worse than granting none.

        Args:
            payload: The provider object from the event.

        Returns:
            uuid.UUID | None: The owning user, or None when it cannot be established.
        """
        raw = (payload.get("metadata") or {}).get("user_id") or payload.get("client_reference_id")
        if isinstance(raw, str):
            try:
                candidate = uuid.UUID(raw)
            except ValueError:
                logging.warning("Billing event carried a user reference that is not a UUID")
            else:
                if await self.CRUDUser.get_by_id(user_id=candidate) is not None:
                    return candidate
                logging.warning("Billing event referenced a user that does not exist")

        return await self._user_id_for_customer(payload.get("customer"))

    async def _user_id_for_customer(self, customer: object) -> uuid.UUID | None:
        """
        Find the user behind a provider customer ID via the subscription mirror.

        Args:
            customer: Raw customer field from the event.

        Returns:
            uuid.UUID | None: The owning user, or None.
        """
        if not isinstance(customer, str):
            return None
        subscriptions = await self.CRUDSubscription.list_by_customer(provider_customer_id=customer)
        return subscriptions[0].user_id if subscriptions else None

    async def _on_checkout_completed(self, *, event: ProviderEvent) -> dict[str, Any]:
        """
        Grant access for a completed one-time purchase.

        Only ``mode=payment`` is granted here. A subscription checkout is granted by its
        ``customer.subscription`` events instead, because those carry the status and the paid-
        through date that decide how long access lasts — a checkout session says a payment
        started, not that a subscription is live.

        An unpaid session is recorded and dropped: Stripe emits this event for asynchronous
        payment methods before the money has actually settled.

        Args:
            event: The verified checkout event.

        Returns:
            dict[str, Any]: What was granted, if anything.
        """
        payload = event.payload
        if payload.get("mode") != "payment":
            return {"action": "deferred_to_subscription_events"}
        if payload.get("payment_status") != "paid":
            logging.info("Checkout session completed without a settled payment; not granting")
            return {"action": "awaiting_payment"}

        user_id = await self._resolve_user_id(payload)
        plan_name = (payload.get("metadata") or {}).get("plan")
        definition = get_plan(plan_name) if isinstance(plan_name, str) else None
        if user_id is None or definition is None or definition.entitlement is None:
            logging.warning("Checkout event could not be attributed to a user and plan")
            return {"action": "unattributable"}

        existing = await self.CRUDEntitlement.get_by_source_event(source_event_id=event.event_id)
        if existing is not None:
            return {"action": "already_granted", "entitlement_id": str(existing.id)}

        now = datetime.now(UTC)
        grant = await self.CRUDEntitlement.create(
            obj_in={
                "user_id": user_id,
                "entitlement": definition.entitlement,
                "active_from": now,
                # A one-time purchase buys a fixed window. Setting the end date at grant time
                # means nothing has to remember to expire it: the active lookup compares the
                # window to the clock on every request.
                "active_until": now + timedelta(days=definition.duration_days)
                if definition.duration_days
                else None,
                "status": EntitlementStatus.ACTIVE,
                "source_event_id": event.event_id,
            }
        )
        logging.info(f"Granted {definition.entitlement} to user {user_id} from a one-time payment")
        await self._announce_grant(
            user_id=user_id,
            plan=str(definition.plan),
            plan_name=definition.name,
            entitlement=str(definition.entitlement),
            access_until=grant.active_until,
        )
        return {"action": "granted", "entitlement_id": str(grant.id)}

    async def _on_subscription_event(self, *, event: ProviderEvent) -> dict[str, Any]:
        """
        Mirror a subscription and bring its entitlement into line with it.

        The mirror and the grant are updated together but stay separate records: the mirror is
        what the provider believes, the grant is what this application will honour. A cancelled
        subscription that is still paid through the end of the month is exactly that difference,
        and merging the two would force a choice between billing the student honestly and giving
        them what they paid for.

        Args:
            event: The verified subscription event.

        Returns:
            dict[str, Any]: What changed.
        """
        normalised = StripeProvider.to_subscription(event.payload)
        if not normalised.provider_subscription_id:
            return {"action": "unattributable"}

        user_id = await self._resolve_user_id(event.payload)
        if user_id is None:
            existing = await self.CRUDSubscription.get_by_provider_id(
                provider_subscription_id=normalised.provider_subscription_id
            )
            user_id = existing.user_id if existing else None
        if user_id is None:
            logging.warning("Subscription event could not be attributed to a user")
            return {"action": "unattributable"}

        stored = await self.CRUDSubscription.get_by_provider_id(
            provider_subscription_id=normalised.provider_subscription_id
        )
        if (
            stored is not None
            and stored.last_event_at is not None
            and event.created_at is not None
            and event.created_at < stored.last_event_at
        ):
            logging.info(
                f"Skipping subscription event {event.event_id}: older than the state already "
                f"applied to {normalised.provider_subscription_id}"
            )
            return {"action": "stale"}

        status = (
            SubscriptionStatus.CANCELED
            if event.event_type == "customer.subscription.deleted"
            else normalised.status
        )
        subscription = await self.CRUDSubscription.upsert_by_provider_id(
            provider_subscription_id=normalised.provider_subscription_id,
            obj_in={
                "user_id": user_id,
                "provider": self.provider.name,
                "provider_customer_id": normalised.provider_customer_id,
                "plan": self._plan_for_price(normalised),
                "status": status,
                "current_period_start": normalised.current_period_start,
                "current_period_end": normalised.current_period_end,
                "cancel_at_period_end": normalised.cancel_at_period_end,
                "last_event_at": event.created_at,
            },
        )

        return await self._sync_subscription_entitlement(
            subscription_id=subscription.id,
            user_id=user_id,
            status=status,
            cancel_at_period_end=normalised.cancel_at_period_end,
            period_end=normalised.current_period_end,
            source_event_id=event.event_id,
        )

    @staticmethod
    def _plan_for_price(subscription: ProviderSubscription) -> str:
        """
        Name the plan a subscription's price corresponds to.

        Falls back to the monthly plan rather than to free: a live subscription is by definition
        not free, and recording it as such would make the mirror lie about a paying customer.

        Args:
            subscription: The normalised provider subscription.

        Returns:
            str: Plan identifier.
        """
        from core.config.settings import settings

        if subscription.price_id and subscription.price_id == settings.STRIPE_PRICE_SEASON_PASS:
            return Plan.SEASON_PASS
        return Plan.PRO_MONTHLY

    async def _sync_subscription_entitlement(
        self,
        *,
        subscription_id: uuid.UUID,
        user_id: uuid.UUID,
        status: str,
        cancel_at_period_end: bool,
        period_end: datetime | None,
        source_event_id: str,
    ) -> dict[str, Any]:
        """
        Create, adjust or revoke the grant a subscription provides.

        Written as a convergence rather than a set of transitions: given the subscription's
        current state, make the grant match. That is what makes replaying events safe — the same
        event applied twice reaches the same place — and it is why a missed event is repaired by
        the next one that arrives rather than leaving the two permanently out of step.

        Args:
            subscription_id: The mirrored subscription.
            user_id: Owning user.
            status: The subscription's current status.
            cancel_at_period_end: Whether the provider will not renew it.
            period_end: The date the current paid period ends.
            source_event_id: Event that caused this change, recorded on a new grant.

        Returns:
            dict[str, Any]: What changed.
        """
        active = await self.CRUDEntitlement.get_active_for_subscription(
            subscription_id=subscription_id
        )

        if status in _GRANTING_STATUSES or status in _GRACE_STATUSES:
            # A cancellation that has not taken effect yet is honoured by giving the grant an end
            # date, not by revoking it. The student paid through the period end and keeps access
            # until then, and expiry then needs no further event to happen.
            active_until = period_end if cancel_at_period_end else None
            if active is None:
                grant = await self.CRUDEntitlement.create(
                    obj_in={
                        "user_id": user_id,
                        "entitlement": Entitlement.PRO,
                        "active_from": datetime.now(UTC),
                        "active_until": active_until,
                        "status": EntitlementStatus.ACTIVE,
                        "source_event_id": source_event_id,
                        "source_subscription_id": subscription_id,
                    }
                )
                logging.info(f"Granted {Entitlement.PRO} to user {user_id} from a subscription")
                await self._announce_grant(
                    user_id=user_id,
                    plan=str(Plan.PRO_MONTHLY),
                    plan_name=PRO_MONTHLY_PLAN.name,
                    entitlement=str(Entitlement.PRO),
                    access_until=active_until,
                )
                return {"action": "granted", "entitlement_id": str(grant.id)}
            if active.active_until != active_until:
                await self.CRUDEntitlement.set_window(
                    entitlement_id=active.id, active_until=active_until
                )
                return {"action": "window_updated", "entitlement_id": str(active.id)}
            return {"action": "unchanged", "entitlement_id": str(active.id)}

        revoked = await self.CRUDEntitlement.revoke_for_subscription(
            subscription_id=subscription_id
        )
        if revoked:
            logging.info(f"Revoked {revoked} grant(s) for user {user_id} after {status}")
        return {"action": "revoked", "revoked": revoked}

    async def _announce_grant(
        self,
        *,
        user_id: uuid.UUID,
        plan: str,
        plan_name: str,
        entitlement: str,
        access_until: datetime | None,
    ) -> None:
        """
        Record the conversion and confirm it to the student.

        Both are side effects of a grant that has already been written, and neither may undo it.
        The event is dispatched without waiting and the email swallows its own failures, because
        this runs inside the webhook: raising here would return a non-2xx to Stripe, which would
        retry the payment event — spending a retry, and risking a support conversation, because a
        mail server was slow.

        ``checkout_completed`` is recorded here rather than on the success page for the same
        reason the entitlement is written here: the browser returning from checkout knows the
        payment succeeded, and that knowledge is not evidence. Only a verified event is.

        Args:
            user_id: The paying student.
            plan: Plan identifier, for the funnel.
            plan_name: Human name of the plan, for the email.
            entitlement: The entitlement granted.
            access_until: When access ends, or None for a renewing subscription.
        """
        await analytics.record(
            event=AnalyticsEvent.CHECKOUT_COMPLETED,
            user_id=user_id,
            properties={"plan": plan, "entitlement": entitlement},
        )
        await self.EmailService.send_payment_receipt(
            user_id=user_id, plan_name=plan_name, access_until=access_until
        )

    async def _on_charge_refunded(self, *, event: ProviderEvent) -> dict[str, Any]:
        """
        Revoke access bought by a payment that has been refunded.

        Only a full refund revokes. A partial refund is a support gesture — a few days of goodwill
        credit, a billing correction — and taking away the whole recruiting season over it would
        turn a resolved complaint into a new one.

        Args:
            event: The verified refund event.

        Returns:
            dict[str, Any]: What was revoked.
        """
        payload = event.payload
        amount = payload.get("amount")
        refunded = payload.get("amount_refunded")
        if not (isinstance(amount, int) and isinstance(refunded, int) and refunded >= amount > 0):
            logging.info("Partial refund recorded; paid access is left in place")
            return {"action": "partial_refund"}

        user_id = await self._resolve_user_id(payload)
        if user_id is None:
            logging.warning("Refund event could not be attributed to a user")
            return {"action": "unattributable"}

        plan_name = (payload.get("metadata") or {}).get("plan")
        definition = get_plan(plan_name) if isinstance(plan_name, str) else None
        revoked = await self.CRUDEntitlement.revoke_for_user(
            user_id=user_id,
            entitlement=definition.entitlement if definition else None,
        )
        logging.info(f"Revoked {revoked} grant(s) for user {user_id} after a full refund")
        return {"action": "revoked", "revoked": revoked}
