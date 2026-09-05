"""Per-category mastery scores.

One row per user per category, recomputed by the nightly rollup rather than on read. Mastery is
read on every dashboard, results page and practice recommendation, but changes only when new
attempts arrive, so a stored value keeps reads cheap and, more importantly, consistent: two
surfaces must never show different mastery for the same category.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from core.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class SkillScore(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A user's current mastery in one category, with the previous value for trend display."""

    __tablename__ = "skill_scores"
    __table_args__ = (
        UniqueConstraint("user_id", "category_slug", name="uq_skill_scores_user_category"),
        CheckConstraint("score BETWEEN 0 AND 100", name="ck_skill_scores_score_range"),
        CheckConstraint(
            "previous_score IS NULL OR previous_score BETWEEN 0 AND 100",
            name="ck_skill_scores_previous_score_range",
        ),
        # A score must be backed by graded attempts. A category showing 72 from zero evidence
        # would be a fabricated readiness signal, which is the one thing this product cannot do.
        CheckConstraint("evidence_count > 0", name="ck_skill_scores_has_evidence"),
        # The dashboard's central question is "what am I weakest at", so scores are read per user
        # in ascending order.
        Index("ix_skill_scores_user_score", "user_id", "score"),
        Index("ix_skill_scores_category", "category_slug"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    category_slug: Mapped[str] = mapped_column(
        ForeignKey("categories.slug", ondelete="RESTRICT"), nullable=False
    )
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    # The value before the most recent recomputation, so the UI can show movement without
    # querying and re-deriving history on every dashboard load.
    previous_score: Mapped[int | None] = mapped_column(SmallInteger)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
