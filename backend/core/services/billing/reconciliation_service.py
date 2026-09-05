"""Repair of billing state that webhooks did not deliver.

Webhooks are the fast path, not the guarantee. A delivery can fail every retry, a deployment can
be down for the whole retry window, and a provider incident can drop events entirely — and every
one of those leaves this application's mirror wrong in a way no amount of retrying inside the
handler can fix, because the event is simply never coming.

Two failures matter and they are asymmetric. A missed cancellation leaves someone with access
they stopped paying for, which costs money. A missed renewal or purchase leaves someone without
access they paid for, which costs a customer. Reconciliation asks the provider what is actually
true and makes the mirror match, so neither one persists past the next sweep.
"""

import uuid

from core import logger
from core.config.settings import settings
from core.constants.enums import SubscriptionStatus
from core.cruds.billing_crud import CRUDEntitlement, CRUDSubscription
from core.services.billing.provider import (
    PaymentError,
    PaymentProvider,
    ProviderSubscription,
    get_payment_provider,
)

logging = logger(__name__)


class ReconciliationService:
    """Brings stored subscriptions and entitlements back in line with the provider."""

    def __init__(self, provider: PaymentProvider | None = None) -> None:
        """
        Initialise the service with a payment provider and the CRUD layers it writes through.

        Args:
            provider: Payment provider to use; defaults to the configured one.
        """
        self.provider = provider or get_payment_provider()
        self.CRUDSubscription = CRUDSubscription()
        self.CRUDEntitlement = CRUDEntitlement()

    async def run(self) -> dict[str, int]:
        """
        Expire elapsed grants and re-check every non-terminal subscription.

        Expiry runs unconditionally and needs no provider: a Season Pass carries its own end date,
        so marking it expired is bookkeeping that keeps the table readable. Access does not depend
        on it having run — ``get_active_for_user`` compares the window to the clock — which is
        exactly why it is safe to run in a job that might be down for a day.

        The provider pass is skipped when Stripe is not configured, so a deployment without
        payments does not log an error every interval for work it has no reason to do.

        Returns:
            dict[str, int]: Counts of what was expired, checked, corrected and failed.

        Raises:
            Exception: If the expiry pass fails; the provider pass reports failures as counts.
        """
        logging.info("Executing ReconciliationService.run")
        summary = {"expired": 0, "checked": 0, "corrected": 0, "failed": 0}
        summary["expired"] = await self.CRUDEntitlement.expire_elapsed()

        if not settings.STRIPE_SECRET_KEY:
            return summary

        for subscription in await self.CRUDSubscription.list_reconcilable():
            if not subscription.provider_subscription_id:
                continue
            summary["checked"] += 1
            try:
                remote = await self.provider.fetch_subscription(
                    subscription_id=subscription.provider_subscription_id
                )
            except PaymentError as error:
                # One unreadable subscription must not abandon the sweep: the next one may be the
                # cancellation that is currently giving away paid access.
                logging.error(f"Reconciliation could not read a subscription: {error}")
                summary["failed"] += 1
                continue

            if await self._correct(subscription_id=subscription.id, remote=remote):
                summary["corrected"] += 1

        if summary["corrected"] or summary["failed"]:
            logging.info(f"ReconciliationService.run {summary}")
        return summary

    async def _correct(self, *, subscription_id: uuid.UUID, remote: ProviderSubscription) -> bool:
        """
        Apply the provider's current view of one subscription, if it differs from the mirror.

        Deliberately narrow: it writes the mirror and revokes access that the provider says has
        ended. It does not *grant*, because granting is what a verified payment event does, and a
        reconciliation sweep is not one. A subscription that is genuinely active but has no grant
        is logged for a human rather than silently fixed — that combination means an event was
        lost, and quietly papering over it would hide the fact that it happens.

        Args:
            subscription_id: The stored subscription's primary key.
            remote: The provider's current view of it.

        Returns:
            bool: True when something was changed.

        Raises:
            Exception: If a write fails.
        """
        stored = await self.CRUDSubscription.get_by_provider_id(
            provider_subscription_id=remote.provider_subscription_id
        )
        if stored is None:
            return False

        changed = (
            stored.status != remote.status
            or stored.cancel_at_period_end != remote.cancel_at_period_end
            or stored.current_period_end != remote.current_period_end
        )
        if changed:
            await self.CRUDSubscription.upsert_by_provider_id(
                provider_subscription_id=remote.provider_subscription_id,
                obj_in={
                    "status": remote.status,
                    "cancel_at_period_end": remote.cancel_at_period_end,
                    "current_period_start": remote.current_period_start,
                    "current_period_end": remote.current_period_end,
                },
            )
            logging.info(
                f"Reconciled subscription {remote.provider_subscription_id} to {remote.status}"
            )

        terminal = remote.status in {SubscriptionStatus.CANCELED, SubscriptionStatus.EXPIRED}
        active = await self.CRUDEntitlement.get_active_for_subscription(
            subscription_id=subscription_id
        )
        if terminal and active is not None:
            revoked = await self.CRUDEntitlement.revoke_for_subscription(
                subscription_id=subscription_id
            )
            logging.warning(
                f"Reconciliation revoked {revoked} grant(s) for a {remote.status} subscription — "
                "a cancellation webhook was never applied"
            )
            return True
        if not terminal and active is None:
            logging.warning(
                f"Subscription {remote.provider_subscription_id} is {remote.status} with no "
                "active grant; a payment event was lost and needs review"
            )
        return changed
