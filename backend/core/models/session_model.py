"""Practice and diagnostic sessions, and their server-decided question composition.

A session's composition is persisted rather than recomputed. Two reasons: a browser refresh must
recover exactly the session that was in progress, and the client must not be able to reshuffle a
session to farm easier questions. The server decides the order once and stores it.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.constants.enums import SessionStatus, SessionType, in_check
from core.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Session(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A diagnostic or practice run belonging to one user."""

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(in_check("type", SessionType), name="ck_sessions_type"),
        CheckConstraint(in_check("status", SessionStatus), name="ck_sessions_status"),
        CheckConstraint("question_count > 0", name="ck_sessions_question_count_positive"),
        # A finished session must record when it finished, and an unfinished one must not claim
        # to have. Without this, "am I improving over time" queries silently include sessions
        # with no end time.
        CheckConstraint(
            "(status = 'in_progress') = (finished_at IS NULL)",
            name="ck_sessions_finished_at_matches_status",
        ),
        # The dashboard and review list both read a user's sessions newest-first.
        Index("ix_sessions_user_started", "user_id", "started_at", postgresql_using="btree"),
        # The results-email sweep looks for finished diagnostics whose email has not gone
        # out. Nearly every row eventually carries a timestamp, so the useful index covers
        # only the ones that do not.
        Index(
            "ix_sessions_results_email_pending",
            "finished_at",
            postgresql_where=text("results_email_sent_at IS NULL AND type = 'diagnostic'"),
        ),
        # Resuming asks "does this user have a session still open?" — a small partial index.
        Index(
            "ix_sessions_user_in_progress",
            "user_id",
            postgresql_where=text("status = 'in_progress'"),
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=SessionStatus.IN_PROGRESS
    )
    question_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # Why these questions were chosen, captured at selection time so the explanation shown to the
    # student ("Valuation is your weakest category, and 2 reviews are due") stays accurate even
    # after their mastery scores move on.
    selection_rationale: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the results email for this diagnostic was sent. Set only on a successful send, so the
    # sweep that finds unsent results retries a failure on its next pass and never sends twice.
    # Kept on the session rather than in a delivery log because "did this diagnostic's results go
    # out" is a fact about the diagnostic.
    results_email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    questions: Mapped[list["SessionQuestion"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SessionQuestion(Base, UUIDPrimaryKeyMixin):
    """One slot in a session's fixed, server-decided question order.

    Pinning the question version here, not only on the attempt, means the student is graded
    against the rubric that was current when the session was composed — a mid-session rubric
    publish cannot change the terms partway through.
    """

    __tablename__ = "session_questions"
    __table_args__ = (
        UniqueConstraint("session_id", "position", name="uq_session_questions_position"),
        # A question may appear at most once per session.
        UniqueConstraint("session_id", "question_id", name="uq_session_questions_question"),
        CheckConstraint("position >= 0", name="ck_session_questions_position_non_negative"),
        Index("ix_session_questions_question", "question_id"),
        Index("ix_session_questions_version", "question_version_id"),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("questions.id", ondelete="RESTRICT"), nullable=False
    )
    question_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("question_versions.id", ondelete="RESTRICT"), nullable=False
    )

    session: Mapped[Session] = relationship(back_populates="questions")
