"""add billing events and subscription event ordering

The durable record of every payment-provider event, and the idempotency guarantee behind paid
access. Stripe delivers at least once and retries any non-2xx response, so duplicate deliveries
are ordinary traffic. Most handlers are naturally idempotent, but a Season Pass is a one-time
payment with no subscription to key on — a replayed ``checkout.session.completed`` would grant a
second pass. The unique constraint here is what prevents that, in the database rather than in
handler logic.

Revision ID: 737f1a7dc773
Revises: a1c4e9f20b31
Create Date: 2026-09-04 18:46:48.188003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "737f1a7dc773"
down_revision: str | None = "a1c4e9f20b31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the billing event log."""
    op.create_table(
        "billing_events",
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column("provider", sa.Text(), server_default="stripe", nullable=False),
        sa.Column("provider_event_id", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="received", nullable=False),
        # When the provider created the event, not when it arrived. Webhooks are delivered out of
        # order, so this is what distinguishes a stale subscription update from a current one.
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        # Identifiers only, never the raw event: a Stripe event carries the customer's name,
        # email and card metadata, none of which is needed here to reconcile a payment.
        sa.Column(
            "summary",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('received', 'processed', 'ignored', 'failed')",
            name="ck_billing_events_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "provider_event_id", name="uq_billing_events_provider_event"
        ),
    )
    op.create_index("ix_billing_events_type", "billing_events", ["event_type"])
    op.create_index("ix_billing_events_status", "billing_events", ["status"])

    # Stripe does not guarantee event ordering, so the mirror records the provider clock of
    # the last event applied to it. Without this an `updated` event redelivered from before a
    # cancellation would overwrite the cancellation and restore paid access.
    op.add_column(
        "subscriptions", sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    """Drop the billing event log and the subscription ordering column."""
    op.drop_column("subscriptions", "last_event_at")
    op.drop_index("ix_billing_events_status", table_name="billing_events")
    op.drop_index("ix_billing_events_type", table_name="billing_events")
    op.drop_table("billing_events")
