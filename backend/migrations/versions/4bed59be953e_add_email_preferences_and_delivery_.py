"""add email preferences and delivery markers

Three columns, no delivery table. Each fact lives on the row it is about: whether a diagnostic's
results have gone out belongs to the diagnostic, and when a student was last nudged belongs to
the student. The sweeps that send these emails set the marker only on success, so a failure is
retried on the next pass and a success is never repeated — which is the same guarantee a delivery
log would give, without a table to keep in step.

Revision ID: 4bed59be953e
Revises: 737f1a7dc773
Create Date: 2026-09-04 19:41:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4bed59be953e"
down_revision: str | None = "737f1a7dc773"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add study-reminder preferences and the two send markers."""
    # Defaults to true, unlike marketing consent, which defaults to false. A study reminder is the
    # product working rather than something being sold, and every one carries a one-click
    # unsubscribe — which is what makes an on-by-default study email defensible and a marketing
    # one not.
    op.add_column(
        "profiles",
        sa.Column(
            "study_reminder_emails",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "profiles", sa.Column("last_nudge_email_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "sessions", sa.Column("results_email_sent_at", sa.DateTime(timezone=True), nullable=True)
    )

    # The nudge sweep asks for reminder-enabled students who have not been nudged recently. A
    # partial index keeps unsubscribed students out of that scan entirely, since they can never
    # be selected.
    op.create_index(
        "ix_profiles_nudge_due",
        "profiles",
        ["last_nudge_email_at"],
        postgresql_where=sa.text("study_reminder_emails"),
    )
    # The results sweep asks for finished diagnostics whose email has not gone out. Nearly every
    # row eventually has a timestamp here, so the useful index is over the ones that do not.
    op.create_index(
        "ix_sessions_results_email_pending",
        "sessions",
        ["finished_at"],
        postgresql_where=sa.text("results_email_sent_at IS NULL AND type = 'diagnostic'"),
    )


def downgrade() -> None:
    """Remove the preferences and send markers."""
    op.drop_index("ix_sessions_results_email_pending", table_name="sessions")
    op.drop_index("ix_profiles_nudge_due", table_name="profiles")
    op.drop_column("sessions", "results_email_sent_at")
    op.drop_column("profiles", "last_nudge_email_at")
    op.drop_column("profiles", "study_reminder_emails")
