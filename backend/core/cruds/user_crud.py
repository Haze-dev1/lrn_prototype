"""Database access for user accounts and student profiles."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_, select

from core import logger
from core.constants.enums import UserStatus
from core.database.database import session
from core.models.user_model import Profile, User

logging = logger(__name__)


class CRUDUser:
    """Database access layer for user accounts."""

    async def create(self, *, obj_in: dict[str, Any]) -> User:
        """
        Insert a new user account.

        The email is normalised to lowercase before insert; the database also enforces this, so a
        caller that skips normalisation gets a constraint violation rather than a duplicate
        account differing only by case.

        Args:
            obj_in: User fields, including at least ``email``.

        Returns:
            User: The created user.

        Raises:
            Exception: If the insert fails, including on duplicate email.
        """
        try:
            logging.info("Executing CRUDUser.create")
            data = dict(obj_in)
            data["email"] = data["email"].strip().lower()
            user = User(**data)
            async with session() as db:
                db.add(user)
                await db.flush()
                await db.refresh(user)
            return user
        except Exception as error:
            logging.error(f"Error in CRUDUser.create: {error}")
            raise error

    async def get_by_id(self, *, user_id: uuid.UUID) -> User | None:
        """
        Read a user by primary key.

        Args:
            user_id: User ID.

        Returns:
            User | None: The user if found, otherwise None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDUser.get_by_id")
            async with session() as db:
                return await db.get(User, user_id)
        except Exception as error:
            logging.error(f"Error in CRUDUser.get_by_id: {error}")
            raise error

    async def get_by_email(self, *, email: str) -> User | None:
        """
        Read a user by email address.

        Normalises the input the same way ``create`` does, so a login attempt with different
        casing still resolves to the same account.

        Args:
            email: Email address, in any casing.

        Returns:
            User | None: The user if found, otherwise None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDUser.get_by_email")
            async with session() as db:
                result = await db.execute(select(User).where(User.email == email.strip().lower()))
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDUser.get_by_email: {error}")
            raise error

    async def get_by_google_sub(self, *, google_sub: str) -> User | None:
        """
        Read a user by Google subject identifier.

        The subject is used rather than the email because it is stable when a user changes their
        Google account email.

        Args:
            google_sub: Google's stable subject identifier.

        Returns:
            User | None: The user if found, otherwise None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDUser.get_by_google_sub")
            async with session() as db:
                result = await db.execute(select(User).where(User.google_sub == google_sub))
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDUser.get_by_google_sub: {error}")
            raise error

    async def update(self, *, user_id: uuid.UUID, obj_in: dict[str, Any]) -> User | None:
        """
        Update a user record by primary key.

        Args:
            user_id: User ID.
            obj_in: Fields to change.

        Returns:
            User | None: The updated user, or None when no such user exists.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDUser.update")
            async with session() as db:
                user = await db.get(User, user_id)
                if user is None:
                    logging.warning(f"No user found with id: {user_id}")
                    return None
                for field, value in obj_in.items():
                    setattr(user, field, value)
                await db.flush()
                await db.refresh(user)
            return user
        except Exception as error:
            logging.error(f"Error in CRUDUser.update: {error}")
            raise error

    async def record_login(self, *, user_id: uuid.UUID) -> None:
        """
        Stamp the user's most recent successful login.

        Args:
            user_id: User ID.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDUser.record_login")
            await self.update(user_id=user_id, obj_in={"last_login_at": datetime.now(UTC)})
        except Exception as error:
            logging.error(f"Error in CRUDUser.record_login: {error}")
            raise error


class CRUDProfile:
    """Database access layer for student profiles."""

    async def create(self, *, user_id: uuid.UUID, obj_in: dict[str, Any] | None = None) -> Profile:
        """
        Insert a profile for a user.

        Recruiting consent is never taken from the caller's payload here; it defaults to false in
        the database and is changed only through the explicit consent path.

        Args:
            user_id: Owning user ID.
            obj_in: Optional profile fields.

        Returns:
            Profile: The created profile.

        Raises:
            Exception: If the insert fails.
        """
        try:
            logging.info("Executing CRUDProfile.create")
            data = dict(obj_in or {})
            data.pop("recruiting_consent", None)
            profile = Profile(user_id=user_id, **data)
            async with session() as db:
                db.add(profile)
                await db.flush()
                await db.refresh(profile)
            return profile
        except Exception as error:
            logging.error(f"Error in CRUDProfile.create: {error}")
            raise error

    async def list_nudge_candidates(
        self, *, not_since: datetime, limit: int = 500
    ) -> list[tuple[User, Profile]]:
        """
        Read students eligible for a weak-area nudge.

        Eligibility is decided in one query rather than by fetching everyone and filtering in
        Python: the account must be active, study reminders must be on, and the student must not
        have been nudged inside the interval. The interval is enforced **per recipient** rather
        than by the job's schedule, so a re-run, a backfill, or two replicas racing cannot
        double-send.

        Whether the student has anything worth being nudged about is decided above this layer,
        which needs their mastery to answer.

        Args:
            not_since: Exclude anyone nudged at or after this time.
            limit: Maximum recipients per sweep.

        Returns:
            list[tuple[User, Profile]]: Eligible recipients with their preferences.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDProfile.list_nudge_candidates")
            async with session() as db:
                result = await db.execute(
                    select(User, Profile)
                    .join(Profile, Profile.user_id == User.id)
                    .where(User.status == UserStatus.ACTIVE)
                    .where(Profile.study_reminder_emails.is_(True))
                    .where(
                        or_(
                            Profile.last_nudge_email_at.is_(None),
                            Profile.last_nudge_email_at < not_since,
                        )
                    )
                    .order_by(Profile.last_nudge_email_at.asc().nulls_first())
                    .limit(limit)
                )
                return [(user, profile) for user, profile in result.all()]
        except Exception as error:
            logging.error(f"Error in CRUDProfile.list_nudge_candidates: {error}")
            raise error

    async def mark_nudge_sent(self, *, user_id: uuid.UUID) -> None:
        """
        Record that a weak-area nudge was delivered to one student.

        Written only after the provider accepted the message. A failed send therefore leaves the
        student eligible for the next sweep instead of silently skipping their week.

        Args:
            user_id: The recipient.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDProfile.mark_nudge_sent")
            async with session() as db:
                profile = await db.get(Profile, user_id)
                if profile is not None:
                    profile.last_nudge_email_at = datetime.now(UTC)
                    await db.flush()
        except Exception as error:
            logging.error(f"Error in CRUDProfile.mark_nudge_sent: {error}")
            raise error

    async def get_by_user_id(self, *, user_id: uuid.UUID) -> Profile | None:
        """
        Read a profile by owning user ID.

        Args:
            user_id: Owning user ID.

        Returns:
            Profile | None: The profile if found, otherwise None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDProfile.get_by_user_id")
            async with session() as db:
                return await db.get(Profile, user_id)
        except Exception as error:
            logging.error(f"Error in CRUDProfile.get_by_user_id: {error}")
            raise error

    async def update(self, *, user_id: uuid.UUID, obj_in: dict[str, Any]) -> Profile | None:
        """
        Update a profile by owning user ID.

        Setting ``recruiting_consent`` also stamps ``recruiting_consent_updated_at``, because the
        database requires consent to carry the timestamp that makes it auditable and revocable.

        Args:
            user_id: Owning user ID.
            obj_in: Fields to change.

        Returns:
            Profile | None: The updated profile, or None when no profile exists.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDProfile.update")
            data = dict(obj_in)
            if "recruiting_consent" in data:
                data["recruiting_consent_updated_at"] = datetime.now(UTC)
            async with session() as db:
                profile = await db.get(Profile, user_id)
                if profile is None:
                    logging.warning(f"No profile found for user: {user_id}")
                    return None
                for field, value in data.items():
                    setattr(profile, field, value)
                await db.flush()
                await db.refresh(profile)
            return profile
        except Exception as error:
            logging.error(f"Error in CRUDProfile.update: {error}")
            raise error
