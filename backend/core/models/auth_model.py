"""Refresh token records.

Refresh tokens are stored rather than made self-validating, because a session must be revocable:
signing out, changing a password, or detecting a stolen token has to invalidate access
immediately, which a signature alone cannot do. Only the hash is stored, so a database disclosure
does not hand out working sessions.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from core.database.base import Base, CreatedAtMixin, UUIDPrimaryKeyMixin


class RefreshToken(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """One issued refresh token, and its place in a rotation family."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (
        # The hot path is looking a presented token up by its hash.
        Index("uq_refresh_tokens_hash", "token_hash", unique=True),
        # Revoking every live session for a user, on sign-out-everywhere or password change.
        Index(
            "ix_refresh_tokens_user_live",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        # Revoking a whole family at once when token reuse is detected.
        Index("ix_refresh_tokens_family", "family_id"),
        Index("ix_refresh_tokens_expires", "expires_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 of the token. See commons.security.hash_refresh_token for why not Argon2.
    token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # Every rotation of one login shares a family ID. If an already-rotated token is presented
    # again, the original was captured, so the entire family is revoked rather than just that
    # token — otherwise the thief and the legitimate user simply keep taking turns.
    family_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
