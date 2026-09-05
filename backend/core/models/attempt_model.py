"""Attempts, grading audit events, and disputed grades.

The attempt is the unit of learning evidence in this product: sessions are organisational, but
every mastery score, review entry, and recommendation is derived from attempts. Several product
invariants that would otherwise live only in application code are enforced here as database
constraints, because an attempt row that violates them corrupts the evidence permanently.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.constants.enums import (
    Band,
    GradeFlagReason,
    GradeFlagStatus,
    GradingStatus,
    ValidationStatus,
    in_check,
)
from core.database.base import Base, CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin

# Server-side guardrail on answer length, matching the product's composer limit. Enforced here as
# a last line of defence: a client that bypasses the form must not be able to send an unbounded
# payload into a paid model call.
MAX_ANSWER_LENGTH = 2000


class Attempt(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A student's answer to one question, and the grade it received."""

    __tablename__ = "attempts"
    __table_args__ = (
        # One attempt per question per session. This makes a duplicate submit — a double click, a
        # retried request, a refresh — impossible to persist twice, at the database level rather
        # than by hoping the application checked first.
        UniqueConstraint("session_id", "question_id", name="uq_attempts_session_question"),
        CheckConstraint(
            in_check("grading_status", GradingStatus), name="ck_attempts_grading_status"
        ),
        CheckConstraint(in_check("band", Band, nullable=True), name="ck_attempts_band"),
        CheckConstraint("score IS NULL OR score BETWEEN 0 AND 100", name="ck_attempts_score_range"),
        CheckConstraint(
            f"char_length(answer) BETWEEN 1 AND {MAX_ANSWER_LENGTH}",
            name="ck_attempts_answer_length",
        ),
        CheckConstraint(
            "time_taken_seconds IS NULL OR time_taken_seconds >= 0",
            name="ck_attempts_time_taken_non_negative",
        ),
        # A graded attempt must carry the evidence that justifies it. A row claiming GRADED with
        # no score or band would render as a blank grade panel with no way to tell why.
        CheckConstraint(
            "grading_status <> 'graded' OR (score IS NOT NULL AND band IS NOT NULL"
            " AND graded_at IS NOT NULL)",
            name="ck_attempts_graded_has_result",
        ),
        # A grading failure must never look like a score of zero. This is the schema-level
        # expression of "an answer is never lost because the AI failed": if the provider could
        # not produce a valid grade, the attempt carries no score at all, and the UI must show a
        # retry state rather than a devastating and wrong 0.
        CheckConstraint(
            "grading_status NOT IN ('pending', 'grading', 'failed')"
            " OR (score IS NULL AND band IS NULL)",
            name="ck_attempts_ungraded_has_no_score",
        ),
        # Review lists and the dashboard read a user's attempts newest-first.
        Index("ix_attempts_user_submitted", "user_id", "submitted_at"),
        # Spaced repetition asks, per user and question, when it was last answered and how it
        # scored. This composite covers that lookup without touching the table.
        Index("ix_attempts_user_question_submitted", "user_id", "question_id", "submitted_at"),
        # The grading retry sweep scans only unfinished work. A partial index stays small no
        # matter how many millions of successfully graded attempts accumulate.
        Index(
            "ix_attempts_unresolved_grading",
            "submitted_at",
            postgresql_where=text("grading_status IN ('pending', 'grading', 'failed')"),
        ),
        Index("ix_attempts_question_version", "question_version_id"),
        Index("ix_attempts_session", "session_id"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    # Denormalised from the session so every ownership check and per-user query is a single-table
    # read. The authorisation check runs on every request touching an attempt; a join there is a
    # cost paid forever to avoid one redundant column.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    # RESTRICT, not CASCADE: a question version can never be deleted while any attempt was graded
    # against it, because that would destroy the provenance of a historical grade.
    question_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT"), nullable=False
    )

    answer: Mapped[str] = mapped_column(Text, nullable=False)
    grading_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=GradingStatus.PENDING
    )

    # --- Populated only once grading succeeds. ---
    score: Mapped[int | None] = mapped_column(SmallInteger)
    band: Mapped[str | None] = mapped_column(Text)
    feedback: Mapped[str | None] = mapped_column(Text)
    concepts_hit: Mapped[list[Any] | None] = mapped_column(JSONB)
    concepts_missed: Mapped[list[Any] | None] = mapped_column(JSONB)
    mistake_flags: Mapped[list[Any] | None] = mapped_column(JSONB)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # ---------------------------------------------

    time_taken_seconds: Mapped[int | None] = mapped_column(Integer)
    retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    grade_events: Mapped[list["GradeEvent"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )


class GradeEvent(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """An audit record of one grading call, successful or not.

    Append-only. Every grade the product has ever shown must be reconstructible: which provider
    and model produced it, under which prompt and rubric version, at what cost and latency, and
    whether the response validated. Without this, a grading regression cannot be attributed and a
    disputed grade cannot be investigated.
    """

    __tablename__ = "grade_events"
    __table_args__ = (
        CheckConstraint(
            in_check("validation_status", ValidationStatus),
            name="ck_grade_events_validation_status",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0", name="ck_grade_events_input_tokens"
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0", name="ck_grade_events_output_tokens"
        ),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="ck_grade_events_latency"),
        Index("ix_grade_events_attempt_created", "attempt_id", "created_at"),
        # Cost and failure-rate reporting scan by time; failures are the rarer, more urgent case.
        Index("ix_grade_events_created", "created_at"),
        Index(
            "ix_grade_events_failures",
            "created_at",
            postgresql_where=text("validation_status <> 'valid'"),
        ),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_request_id: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    model_version: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text, nullable=False)
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    # Numeric, not float: per-call costs are fractions of a cent and are summed across millions of
    # rows, where binary floating point drift becomes a real reporting error.
    estimated_cost: Mapped[Any | None] = mapped_column(Numeric(12, 6))
    # The provider payload as received, for replaying a disputed grade. Never returned to clients:
    # it can contain model reasoning the product deliberately does not expose.
    raw_response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    validation_status: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default=text("0"))

    attempt: Mapped[Attempt] = relationship(back_populates="grade_events")


class GradeFlag(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A student's dispute of a grade, and its admin resolution.

    Flags are a quality signal, not a ticket queue: a cluster of flags on one question usually
    means the rubric is wrong, not that the students are.
    """

    __tablename__ = "grade_flags"
    __table_args__ = (
        # One flag per user per attempt: a dispute is a statement, not a vote to be repeated.
        UniqueConstraint("attempt_id", "user_id", name="uq_grade_flags_attempt_user"),
        CheckConstraint(in_check("reason", GradeFlagReason), name="ck_grade_flags_reason"),
        CheckConstraint(in_check("status", GradeFlagStatus), name="ck_grade_flags_status"),
        CheckConstraint(
            "(status IN ('resolved', 'rejected')) = (resolved_at IS NOT NULL)",
            name="ck_grade_flags_resolved_at_matches_status",
        ),
        # The admin queue reads only open flags, oldest first.
        Index(
            "ix_grade_flags_open",
            "created_at",
            postgresql_where=text("status IN ('open', 'reviewing')"),
        ),
        Index("ix_grade_flags_user", "user_id"),
        Index("ix_grade_flags_reviewer", "reviewer_id"),
    )

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("attempts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=GradeFlagStatus.OPEN)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
