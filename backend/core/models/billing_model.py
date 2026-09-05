"""Subscriptions and server-authoritative entitlements.

These are two different things and are deliberately not merged. A ``subscription`` mirrors what
the payment provider believes; an ``entitlement`` is what this application will actually let a
user do. Keeping them separate means a delayed, duplicated or out-of-order webhook changes the
mirror without silently granting or revoking access, and access can be granted manually (support,
comp) without inventing a fake subscription.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from core.constants.enums import (
    BillingEventStatus,
    Entitlement,
    EntitlementStatus,
    Plan,
    SubscriptionStatus,
    in_check,
)
from core.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Subscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A mirror of the payment provider's subscription state. Never the access decision."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(in_check("plan", Plan), name="ck_subscriptions_plan"),
        CheckConstraint(in_check("status", SubscriptionStatus), name="ck_subscriptions_status"),
        CheckConstraint(
            "current_period_end IS NULL OR current_period_start IS NULL"
            " OR current_period_end > current_period_start",
            name="ck_subscriptions_period_ordered",
        ),
        # The provider's subscription ID is the natural key for webhook reconciliation, so a
        # replayed or duplicated event updates the existing row instead of inserting a second one.
        UniqueConstraint("provider_subscription_id", name="uq_subscriptions_provider_id"),
        Index("ix_subscriptions_user", "user_id"),
        Index("ix_subscriptions_customer", "provider_customer_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="stripe")
    provider_customer_id: Mapped[str | None] = mapped_column(Text)
    provider_subscription_id: Mapped[str | None] = mapped_column(Text)
    plan: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # When the provider created the most recent event applied to this row. Stripe delivers events
    # at least once and explicitly does not guarantee order, so a retried `updated` from before a
    # cancellation can arrive after it. Comparing provider clocks — not local write times — is
    # what stops that resurrecting a cancelled subscription and handing back paid access.
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserEntitlement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A grant of paid access, written only from a verified payment event.

    Free access is the absence of an active row here, never a row with a "free" value, so every
    gated operation asks one question: does an active, unexpired grant exist for this user?
    """

    __tablename__ = "entitlements"
    __table_args__ = (
        CheckConstraint(in_check("entitlement", Entitlement), name="ck_entitlements_entitlement"),
        CheckConstraint(in_check("status", EntitlementStatus), name="ck_entitlements_status"),
        CheckConstraint(
            "active_until IS NULL OR active_until > active_from",
            name="ck_entitlements_window_ordered",
        ),
        # The hot path on every gated request: "is there an active grant for this user?". A
        # partial index keeps revoked and expired history out of that lookup entirely.
        Index(
            "ix_entitlements_user_active",
            "user_id",
            "active_until",
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_entitlements_subscription", "source_subscription_id"),
        Index("ix_entitlements_source_event", "source_event_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    entitlement: Mapped[str] = mapped_column(Text, nullable=False)
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Null means open-ended: the grant lasts while its subscription stays active. A Season Pass
    # sets a concrete end date.
    active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=EntitlementStatus.ACTIVE
    )
    # The provider event that caused this grant. Recorded so a grant can always be traced back to
    # a verified webhook rather than to an unexplained write.
    source_event_id: Mapped[str | None] = mapped_column(Text)
    source_subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="SET NULL")
    )


class BillingEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One payment-provider event, recorded before it is acted on.

    This table is the idempotency guarantee, and it is a table rather than a Redis key because
    losing it would mean granting access twice. Stripe delivers at least once and retries on any
    non-2xx, so duplicates are ordinary traffic, not an anomaly. Most handlers are naturally
    idempotent — the subscription mirror upserts, a revoke of an already-revoked grant is a
    no-op — but a Season Pass is a one-time payment with no subscription to key on, so a replayed
    ``checkout.session.completed`` would hand out a second pass. The unique constraint below is
    what actually stops that; the handler logic is not.

    It doubles as the audit trail behind every entitlement: ``entitlements.source_event_id``
    points here, so a grant can always be traced back to a verified, recorded event.
    """

    __tablename__ = "billing_events"
    __table_args__ = (
        CheckConstraint(in_check("status", BillingEventStatus), name="ck_billing_events_status"),
        # The whole point of the table. Insert-then-act: a duplicate delivery loses the race at
        # the database and is answered 200 without re-running the handler.
        UniqueConstraint("provider", "provider_event_id", name="uq_billing_events_provider_event"),
        Index("ix_billing_events_type", "event_type"),
        Index("ix_billing_events_status", "status"),
    )

    provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="stripe")
    provider_event_id: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=BillingEventStatus.RECEIVED
    )
    # When the provider created the event, not when it arrived. Webhooks are delivered out of
    # order, so this is what tells a stale subscription update from a current one.
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Identifiers only — never the raw event. A Stripe event carries the customer's name, email
    # and card metadata, and none of that needs to live in this database to reconcile a payment.
    summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text)
