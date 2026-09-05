"""Database access for refresh tokens and session revocation."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.engine import CursorResult

from core import logger
from core.config.settings import settings
from core.database.database import session
from core.models.auth_model import RefreshToken

logging = logger(__name__)


class CRUDRefreshToken:
    """Database access layer for issued refresh tokens."""

    async def create(
        self, *, user_id: uuid.UUID, token_hash: str, family_id: uuid.UUID | None = None
    ) -> RefreshToken:
        """
        Store a newly issued refresh token.

        A new login starts its own rotation family; a rotation continues the existing one, so
        reuse of any token in the chain can revoke every descendant of the same original login.

        Args:
            user_id: Owning user ID.
            token_hash: SHA-256 hash of the issued token.
            family_id: Existing family to continue, or None to start a new one.

        Returns:
            RefreshToken: The stored token record.

        Raises:
            Exception: If the insert fails.
        """
        try:
            logging.info("Executing CRUDRefreshToken.create")
            record = RefreshToken(
                user_id=user_id,
                token_hash=token_hash,
                family_id=family_id or uuid.uuid4(),
                expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
            )
            async with session() as db:
                db.add(record)
                await db.flush()
                await db.refresh(record)
            return record
        except Exception as error:
            logging.error(f"Error in CRUDRefreshToken.create: {error}")
            raise error

    async def get_by_hash(self, *, token_hash: str) -> RefreshToken | None:
        """
        Read a refresh token record by its hash.

        Returns revoked and expired records too: the caller must be able to tell "already used" —
        which signals theft — from "never existed".

        Args:
            token_hash: SHA-256 hash of the presented token.

        Returns:
            RefreshToken | None: The record if one exists, otherwise None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDRefreshToken.get_by_hash")
            async with session() as db:
                result = await db.execute(
                    select(RefreshToken).where(RefreshToken.token_hash == token_hash)
                )
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDRefreshToken.get_by_hash: {error}")
            raise error

    async def revoke(self, *, token_id: uuid.UUID) -> None:
        """
        Revoke a single refresh token.

        Args:
            token_id: Token record ID.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDRefreshToken.revoke")
            async with session() as db:
                await db.execute(
                    update(RefreshToken)
                    .where(RefreshToken.id == token_id)
                    .where(RefreshToken.revoked_at.is_(None))
                    .values(revoked_at=datetime.now(UTC))
                )
        except Exception as error:
            logging.error(f"Error in CRUDRefreshToken.revoke: {error}")
            raise error

    async def revoke_family(self, *, family_id: uuid.UUID) -> int:
        """
        Revoke every live token in one rotation family.

        Called when an already-rotated token is presented again, which means the token was
        captured. Revoking only the reused token would leave the attacker and the legitimate user
        alternating rotations indefinitely.

        Args:
            family_id: Rotation family to revoke.

        Returns:
            int: Number of tokens revoked.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDRefreshToken.revoke_family")
            async with session() as db:
                result: CursorResult = await db.execute(  # type: ignore[assignment]
                    update(RefreshToken)
                    .where(RefreshToken.family_id == family_id)
                    .where(RefreshToken.revoked_at.is_(None))
                    .values(revoked_at=datetime.now(UTC))
                )
                return int(result.rowcount or 0)
        except Exception as error:
            logging.error(f"Error in CRUDRefreshToken.revoke_family: {error}")
            raise error

    async def revoke_all_for_user(self, *, user_id: uuid.UUID) -> int:
        """
        Revoke every live refresh token belonging to a user.

        Used on sign-out-everywhere, password change, and account deletion, so no previously
        issued session survives the event.

        Args:
            user_id: Owning user ID.

        Returns:
            int: Number of tokens revoked.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDRefreshToken.revoke_all_for_user")
            async with session() as db:
                result: CursorResult = await db.execute(  # type: ignore[assignment]
                    update(RefreshToken)
                    .where(RefreshToken.user_id == user_id)
                    .where(RefreshToken.revoked_at.is_(None))
                    .values(revoked_at=datetime.now(UTC))
                )
                return int(result.rowcount or 0)
        except Exception as error:
            logging.error(f"Error in CRUDRefreshToken.revoke_all_for_user: {error}")
            raise error

    async def delete_expired(self, *, older_than_days: int = 7) -> int:
        """
        Delete refresh tokens that expired some time ago.

        Housekeeping for the scheduler. A grace period is kept after expiry so a token presented
        just after it lapsed is still recognised as expired rather than as never having existed,
        which keeps the theft-detection signal meaningful.

        Args:
            older_than_days: Grace period after expiry before deletion.

        Returns:
            int: Number of records deleted.

        Raises:
            Exception: If the delete fails.
        """
        try:
            logging.info("Executing CRUDRefreshToken.delete_expired")
            cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
            async with session() as db:
                result: CursorResult = await db.execute(  # type: ignore[assignment]
                    delete(RefreshToken).where(RefreshToken.expires_at < cutoff)
                )
                return int(result.rowcount or 0)
        except Exception as error:
            logging.error(f"Error in CRUDRefreshToken.delete_expired: {error}")
            raise error
