"""Database access for subscriptions and server-authoritative entitlements."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert

from core import logger
from core.constants.enums import BillingEventStatus, EntitlementStatus, SubscriptionStatus
from core.database.database import session
from core.models.billing_model import BillingEvent, Subscription, UserEntitlement

logging = logger(__name__)


class CRUDSubscription:
    """Database access layer for the payment provider's subscription mirror."""

    async def upsert_by_provider_id(
        self, *, provider_subscription_id: str, obj_in: dict[str, Any]
    ) -> Subscription:
        """
        Insert or update the mirror of a provider subscription.

        Keyed on the provider's subscription ID so a webhook that is delivered twice, or delivered
        out of order and then replayed, updates one row instead of accumulating duplicates.

        Args:
            provider_subscription_id: The provider's subscription identifier.
            obj_in: Subscription fields to write.

        Returns:
            Subscription: The stored subscription.

        Raises:
            Exception: If the write fails.
        """
        try:
            logging.info("Executing CRUDSubscription.upsert_by_provider_id")
            async with session() as db:
                result = await db.execute(
                    select(Subscription).where(
                        Subscription.provider_subscription_id == provider_subscription_id
                    )
                )
                subscription = result.scalar_one_or_none()
                if subscription is None:
                    subscription = Subscription(
                        provider_subscription_id=provider_subscription_id, **obj_in
                    )
                    db.add(subscription)
                else:
                    for field, value in obj_in.items():
                        setattr(subscription, field, value)
                await db.flush()
                await db.refresh(subscription)
            return subscription
        except Exception as error:
            logging.error(f"Error in CRUDSubscription.upsert_by_provider_id: {error}")
            raise error

    async def get_by_provider_id(self, *, provider_subscription_id: str) -> Subscription | None:
        """
        Read the mirror of one provider subscription.

        Args:
            provider_subscription_id: The provider's subscription identifier.

        Returns:
            Subscription | None: The stored subscription, or None when never mirrored.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSubscription.get_by_provider_id")
            async with session() as db:
                result = await db.execute(
                    select(Subscription).where(
                        Subscription.provider_subscription_id == provider_subscription_id
                    )
                )
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDSubscription.get_by_provider_id: {error}")
            raise error

    async def get_customer_id_for_user(self, *, user_id: uuid.UUID) -> str | None:
        """
        Find the provider customer ID a user already has, if any.

        Reused when starting a second checkout so one student maps to one billing customer.
        Without it a student who buys a Season Pass and later subscribes would exist twice at the
        provider, and the Customer Portal would show them only half their history.

        Args:
            user_id: User to look up.

        Returns:
            str | None: The most recent provider customer ID, or None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSubscription.get_customer_id_for_user")
            async with session() as db:
                result = await db.execute(
                    select(Subscription.provider_customer_id)
                    .where(Subscription.user_id == user_id)
                    .where(Subscription.provider_customer_id.is_not(None))
                    .order_by(Subscription.created_at.desc())
                    .limit(1)
                )
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDSubscription.get_customer_id_for_user: {error}")
            raise error

    async def list_by_customer(self, *, provider_customer_id: str) -> list[Subscription]:
        """
        Read the subscriptions belonging to one provider customer.

        The fallback path for attributing an event that carries no metadata — anything produced
        by the Customer Portal, where this application sets none.

        Args:
            provider_customer_id: The provider's customer identifier.

        Returns:
            list[Subscription]: Matching subscriptions, newest first.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSubscription.list_by_customer")
            async with session() as db:
                result = await db.execute(
                    select(Subscription)
                    .where(Subscription.provider_customer_id == provider_customer_id)
                    .order_by(Subscription.created_at.desc())
                )
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDSubscription.list_by_customer: {error}")
            raise error

    async def list_reconcilable(self, *, limit: int = 200) -> list[Subscription]:
        """
        Read subscriptions whose provider state may have moved on without a webhook.

        Anything not in a terminal state is a candidate: a missed ``customer.subscription.deleted``
        leaves an active mirror that keeps granting access to someone who cancelled, and no amount
        of retrying inside the webhook handler fixes an event that was never delivered.

        Args:
            limit: Maximum subscriptions to return in one sweep.

        Returns:
            list[Subscription]: Non-terminal subscriptions, oldest-checked first.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSubscription.list_reconcilable")
            terminal = (SubscriptionStatus.CANCELED, SubscriptionStatus.EXPIRED)
            async with session() as db:
                result = await db.execute(
                    select(Subscription)
                    .where(Subscription.provider_subscription_id.is_not(None))
                    .where(Subscription.status.not_in(terminal))
                    .order_by(Subscription.updated_at.asc())
                    .limit(limit)
                )
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDSubscription.list_reconcilable: {error}")
            raise error

    async def list_for_user(self, *, user_id: uuid.UUID) -> list[Subscription]:
        """
        Read a user's subscriptions, newest first.

        Args:
            user_id: Owning user ID.

        Returns:
            list[Subscription]: Subscriptions ordered newest first.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSubscription.list_for_user")
            async with session() as db:
                result = await db.execute(
                    select(Subscription)
                    .where(Subscription.user_id == user_id)
                    .order_by(Subscription.created_at.desc())
                )
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDSubscription.list_for_user: {error}")
            raise error


class CRUDEntitlement:
    """Database access layer for paid access grants."""

    async def create(self, *, obj_in: dict[str, Any]) -> UserEntitlement:
        """
        Record a grant of paid access.

        Callers must have verified the originating payment event first: this table is the only
        thing standing between a request and paid functionality.

        Args:
            obj_in: Entitlement fields including user, entitlement, window and source event.

        Returns:
            UserEntitlement: The created grant.

        Raises:
            Exception: If the insert fails.
        """
        try:
            logging.info("Executing CRUDEntitlement.create")
            entitlement = UserEntitlement(**obj_in)
            async with session() as db:
                db.add(entitlement)
                await db.flush()
                await db.refresh(entitlement)
            return entitlement
        except Exception as error:
            logging.error(f"Error in CRUDEntitlement.create: {error}")
            raise error

    async def get_active_for_user(self, *, user_id: uuid.UUID) -> UserEntitlement | None:
        """
        Read a user's currently valid paid access grant, if any.

        This is the authoritative access check, run on every gated operation. Expiry is evaluated
        against the current time in the query rather than trusting a stored status, so a Season
        Pass whose end date has passed stops granting access immediately, without waiting for a
        reconciliation job to mark it expired. Matches the partial index on active entitlements.

        Args:
            user_id: User to check.

        Returns:
            UserEntitlement | None: The active grant, or None when the user is on the free tier.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDEntitlement.get_active_for_user")
            now = datetime.now(UTC)
            async with session() as db:
                result = await db.execute(
                    select(UserEntitlement)
                    .where(UserEntitlement.user_id == user_id)
                    .where(UserEntitlement.status == EntitlementStatus.ACTIVE)
                    .where(UserEntitlement.active_from <= now)
                    .where(
                        or_(
                            UserEntitlement.active_until.is_(None),
                            UserEntitlement.active_until > now,
                        )
                    )
                    .order_by(UserEntitlement.active_from.desc())
                    .limit(1)
                )
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDEntitlement.get_active_for_user: {error}")
            raise error

    async def get_latest_for_user(self, *, user_id: uuid.UUID) -> UserEntitlement | None:
        """
        Read a user's most recent grant whatever its state.

        Distinct from ``get_active_for_user`` because "you had access and it ended" is a different
        message from "you have never had access", and the second is what a student sees if the
        interface only ever asks about active grants. A lapsed Season Pass needs to say when it
        expired and offer the renewal path.

        Args:
            user_id: User to look up.

        Returns:
            UserEntitlement | None: The most recent grant, or None when there has never been one.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDEntitlement.get_latest_for_user")
            async with session() as db:
                result = await db.execute(
                    select(UserEntitlement)
                    .where(UserEntitlement.user_id == user_id)
                    .order_by(UserEntitlement.active_from.desc())
                    .limit(1)
                )
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDEntitlement.get_latest_for_user: {error}")
            raise error

    async def get_by_source_event(self, *, source_event_id: str) -> UserEntitlement | None:
        """
        Find the grant a given payment event already produced.

        The second line of defence behind the unique constraint on billing events: if an event is
        somehow processed twice, this is what stops it granting twice.

        Args:
            source_event_id: Provider event identifier.

        Returns:
            UserEntitlement | None: The grant that event produced, or None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDEntitlement.get_by_source_event")
            async with session() as db:
                result = await db.execute(
                    select(UserEntitlement).where(
                        UserEntitlement.source_event_id == source_event_id
                    )
                )
                return result.scalars().first()
        except Exception as error:
            logging.error(f"Error in CRUDEntitlement.get_by_source_event: {error}")
            raise error

    async def revoke_for_subscription(self, *, subscription_id: uuid.UUID) -> int:
        """
        Revoke every active grant originating from one subscription.

        Used when a subscription is cancelled or refunded. Returns the count so the caller can log
        whether anything was actually revoked, which matters when reconciling a disputed payment.

        Args:
            subscription_id: Source subscription ID.

        Returns:
            int: Number of grants revoked.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDEntitlement.revoke_for_subscription")
            async with session() as db:
                result = await db.execute(
                    select(UserEntitlement)
                    .where(UserEntitlement.source_subscription_id == subscription_id)
                    .where(UserEntitlement.status == EntitlementStatus.ACTIVE)
                )
                grants = list(result.scalars().all())
                for grant in grants:
                    grant.status = EntitlementStatus.REVOKED
                await db.flush()
            return len(grants)
        except Exception as error:
            logging.error(f"Error in CRUDEntitlement.revoke_for_subscription: {error}")
            raise error

    async def revoke_for_user(self, *, user_id: uuid.UUID, entitlement: str | None = None) -> int:
        """
        Revoke a user's active grants, optionally only those of one kind.

        Needed for a refunded one-time purchase, which has no subscription to revoke by: a Season
        Pass grant's only link back to the payment is the event that created it.

        Args:
            user_id: Owning user.
            entitlement: Restrict to one entitlement kind, or None for all of them.

        Returns:
            int: Number of grants revoked.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDEntitlement.revoke_for_user")
            async with session() as db:
                query = (
                    select(UserEntitlement)
                    .where(UserEntitlement.user_id == user_id)
                    .where(UserEntitlement.status == EntitlementStatus.ACTIVE)
                )
                if entitlement is not None:
                    query = query.where(UserEntitlement.entitlement == entitlement)
                grants = list((await db.execute(query)).scalars().all())
                for grant in grants:
                    grant.status = EntitlementStatus.REVOKED
                await db.flush()
            return len(grants)
        except Exception as error:
            logging.error(f"Error in CRUDEntitlement.revoke_for_user: {error}")
            raise error

    async def set_window(
        self, *, entitlement_id: uuid.UUID, active_until: datetime | None
    ) -> UserEntitlement | None:
        """
        Move an existing grant's end date.

        This is how a subscription cancellation is honoured without taking access away early: the
        grant stops being open-ended and gains the paid-through date instead, and expiry then
        happens on its own because the active lookup evaluates the window against the clock.

        Args:
            entitlement_id: Grant to adjust.
            active_until: New end date, or None to make it open-ended again.

        Returns:
            UserEntitlement | None: The updated grant, or None when it no longer exists.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDEntitlement.set_window")
            async with session() as db:
                grant = await db.get(UserEntitlement, entitlement_id)
                if grant is None:
                    return None
                grant.active_until = active_until
                await db.flush()
                await db.refresh(grant)
            return grant
        except Exception as error:
            logging.error(f"Error in CRUDEntitlement.set_window: {error}")
            raise error

    async def get_active_for_subscription(
        self, *, subscription_id: uuid.UUID
    ) -> UserEntitlement | None:
        """
        Read the active grant a subscription is currently providing.

        Args:
            subscription_id: Source subscription.

        Returns:
            UserEntitlement | None: The active grant, or None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDEntitlement.get_active_for_subscription")
            async with session() as db:
                result = await db.execute(
                    select(UserEntitlement)
                    .where(UserEntitlement.source_subscription_id == subscription_id)
                    .where(UserEntitlement.status == EntitlementStatus.ACTIVE)
                    .order_by(UserEntitlement.active_from.desc())
                    .limit(1)
                )
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDEntitlement.get_active_for_subscription: {error}")
            raise error

    async def expire_elapsed(self) -> int:
        """
        Mark active grants whose end date has passed as expired.

        Housekeeping for the reconciliation job only. Access decisions never depend on it having
        run, because ``get_active_for_user`` evaluates expiry against the current time.

        Returns:
            int: Number of grants marked expired.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDEntitlement.expire_elapsed")
            now = datetime.now(UTC)
            async with session() as db:
                result = await db.execute(
                    select(UserEntitlement)
                    .where(UserEntitlement.status == EntitlementStatus.ACTIVE)
                    .where(UserEntitlement.active_until.is_not(None))
                    .where(UserEntitlement.active_until <= now)
                )
                grants = list(result.scalars().all())
                for grant in grants:
                    grant.status = EntitlementStatus.EXPIRED
                await db.flush()
            if grants:
                logging.info(f"Expired {len(grants)} elapsed entitlements")
            return len(grants)
        except Exception as error:
            logging.error(f"Error in CRUDEntitlement.expire_elapsed: {error}")
            raise error


class CRUDBillingEvent:
    """Database access layer for the payment event log.

    The methods here are an insert-then-act protocol, not plain CRUD. ``claim`` inserts the event
    and reports whether this caller is the one that gets to process it; the duplicate that lost
    the race gets False and does nothing. That ordering is what makes webhook handling idempotent
    under Stripe's at-least-once delivery, and it is enforced by a unique constraint rather than
    by a check-then-write that two concurrent deliveries would both pass.
    """

    async def claim(
        self,
        *,
        provider: str,
        provider_event_id: str,
        event_type: str,
        occurred_at: datetime | None,
        summary: dict[str, Any],
    ) -> tuple[BillingEvent, bool]:
        """
        Record a received event, reporting whether this caller should process it.

        A delivery of an event already recorded as ``processed`` or ``ignored`` is the ordinary
        duplicate and does nothing. A delivery of one recorded as ``failed`` or still ``received``
        is *not*: the first is a handler that errored and that the provider is now retrying — the
        retry is the whole reason a failure returns a 5xx — and the second is a handler that never
        finished, which is what a crash mid-processing leaves behind. Refusing to reprocess those
        would strand the event permanently, because the provider only ever sends the same event ID.

        Reprocessing is safe because each handler converges: a grant is guarded by its source
        event, the subscription mirror upserts on the provider's key, and a revoke of an already
        revoked grant is a no-op.

        Args:
            provider: Payment provider name.
            provider_event_id: The provider's event identifier.
            event_type: Provider event type.
            occurred_at: When the provider created the event.
            summary: Identifiers only — never the raw provider payload.

        Returns:
            tuple[BillingEvent, bool]: The stored event, and whether to run the handler.

        Raises:
            Exception: If the write fails for a reason other than a duplicate.
        """
        try:
            logging.info("Executing CRUDBillingEvent.claim")
            async with session() as db:
                # ON CONFLICT DO NOTHING rather than a SELECT then an INSERT: two simultaneous
                # deliveries of the same event would both pass a prior existence check, and both
                # would then grant.
                result = await db.execute(
                    insert(BillingEvent)
                    .values(
                        provider=provider,
                        provider_event_id=provider_event_id,
                        event_type=event_type,
                        occurred_at=occurred_at,
                        summary=summary,
                        status=BillingEventStatus.RECEIVED,
                    )
                    .on_conflict_do_nothing(constraint="uq_billing_events_provider_event")
                    .returning(BillingEvent)
                )
                created = result.scalar_one_or_none()
                if created is not None:
                    await db.flush()
                    await db.refresh(created)
                    return created, True

                existing = (
                    await db.execute(
                        select(BillingEvent)
                        .where(BillingEvent.provider == provider)
                        .where(BillingEvent.provider_event_id == provider_event_id)
                    )
                ).scalar_one()

                unfinished = existing.status in (
                    BillingEventStatus.RECEIVED,
                    BillingEventStatus.FAILED,
                )
                if unfinished:
                    existing.status = BillingEventStatus.RECEIVED
                    existing.error = None
                    existing.processed_at = None
                    await db.flush()
                    await db.refresh(existing)
                    logging.info(
                        f"Reprocessing billing event {provider_event_id}, previously unfinished"
                    )
                return existing, unfinished
        except Exception as error:
            logging.error(f"Error in CRUDBillingEvent.claim: {error}")
            raise error

    async def finish(
        self, *, event_id: uuid.UUID, status: str, error: str | None = None
    ) -> BillingEvent | None:
        """
        Record the outcome of processing one event.

        Args:
            event_id: Billing event to update.
            status: Terminal status from ``BillingEventStatus``.
            error: Failure reason, when the handler raised.

        Returns:
            BillingEvent | None: The updated event, or None when it no longer exists.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDBillingEvent.finish")
            async with session() as db:
                event = await db.get(BillingEvent, event_id)
                if event is None:
                    return None
                event.status = status
                event.error = error
                event.processed_at = datetime.now(UTC)
                await db.flush()
                await db.refresh(event)
            return event
        except Exception as db_error:
            logging.error(f"Error in CRUDBillingEvent.finish: {db_error}")
            raise db_error

    async def get_by_provider_id(
        self, *, provider: str, provider_event_id: str
    ) -> BillingEvent | None:
        """
        Read one recorded event by its provider identifier.

        Args:
            provider: Payment provider name.
            provider_event_id: The provider's event identifier.

        Returns:
            BillingEvent | None: The stored event, or None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDBillingEvent.get_by_provider_id")
            async with session() as db:
                result = await db.execute(
                    select(BillingEvent)
                    .where(BillingEvent.provider == provider)
                    .where(BillingEvent.provider_event_id == provider_event_id)
                )
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDBillingEvent.get_by_provider_id: {error}")
            raise error
