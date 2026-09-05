"""User identity and student profile.

Identity (credentials, status, admin rights) is separated from profile (school, target role,
consent) because they have different sensitivity and different write paths: the profile is
user-editable, while status and admin rights are not.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.constants.enums import TargetRole, UserStatus, in_check
from core.database.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An authenticated account."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(in_check("status", UserStatus), name="ck_users_status"),
        # Emails are stored already normalised, so lookups are a plain equality match on an
        # ordinary unique index rather than a functional index on lower(email).
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
        # An account must retain at least one way to authenticate. Without this, unlinking Google
        # from a password-less account would silently create an account nobody can sign in to.
        CheckConstraint(
            "password_hash IS NOT NULL OR google_sub IS NOT NULL",
            name="ck_users_has_auth_method",
        ),
    )

    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Null for accounts created through Google that never set a password.
    password_hash: Mapped[str | None] = mapped_column(Text)
    # Google's subject identifier. Stable across email changes, unlike the email address.
    google_sub: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=UserStatus.ACTIVE)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    profile: Mapped["Profile"] = relationship(back_populates="user", uselist=False)


class Profile(Base, TimestampMixin):
    """Student-supplied profile and privacy preferences."""

    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint(
            in_check("target_role", TargetRole, nullable=True), name="ck_profiles_target_role"
        ),
        CheckConstraint(
            "graduation_year IS NULL OR graduation_year BETWEEN 1950 AND 2100",
            name="ck_profiles_graduation_year_range",
        ),
        # Recruiting consent must be revocable and auditable, so a timestamp is recorded whenever
        # it is granted. Consent set without a timestamp would be unprovable.
        CheckConstraint(
            "recruiting_consent IS FALSE OR recruiting_consent_updated_at IS NOT NULL",
            name="ck_profiles_consent_has_timestamp",
        ),
        Index("ix_profiles_recruiting_consent", "recruiting_consent"),
        # The nudge sweep selects reminder-enabled students not nudged recently. A partial
        # index keeps unsubscribed students out of that scan entirely.
        Index(
            "ix_profiles_nudge_due",
            "last_nudge_email_at",
            postgresql_where=text("study_reminder_emails"),
        ),
    )

    # The profile is an extension of exactly one user, so the foreign key is also the primary key.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    school: Mapped[str | None] = mapped_column(Text)
    graduation_year: Mapped[int | None] = mapped_column(SmallInteger)
    target_role: Mapped[str | None] = mapped_column(Text)
    # Defaults to false and is independent of account creation: consent is never implied by
    # signing up, and the default must survive a client that omits the field.
    recruiting_consent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    recruiting_consent_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    marketing_emails_opt_in: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # Study reminders default ON, unlike marketing, which defaults off. They are the product
    # working rather than something sold: a spaced-repetition tool that never tells you something
    # is due has quietly stopped being one. Every nudge carries a one-click unsubscribe, which is
    # what makes the default defensible — the student can stop it without signing in.
    study_reminder_emails: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # When the last weak-area nudge was sent. The gap is enforced per recipient rather than by
    # the job's schedule, so a re-run, a backfill or a second replica cannot double-send.
    last_nudge_email_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="profile")
