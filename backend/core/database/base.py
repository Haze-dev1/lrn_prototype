"""SQLAlchemy declarative base and shared column conventions."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base class for every persistence model in the application."""


class UUIDPrimaryKeyMixin:
    """Adds a database-generated UUIDv7 primary key.

    UUIDs keep identifiers non-enumerable, so an attempt or session ID in a URL reveals nothing
    about how many exist. Version 7 is used rather than version 4 because it is time-ordered:
    random v4 keys scatter inserts across the index and fragment it as the table grows, while v7
    values append, which matters for the attempt and grade-event tables that grow fastest.
    Requires PostgreSQL 18+, where ``uuidv7()`` is built in.
    """

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))


class CreatedAtMixin:
    """Adds a server-managed creation timestamp only.

    Used by append-only tables such as question versions and grade events, where the absence of
    ``updated_at`` is itself the point: those rows are immutable once written.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TimestampMixin:
    """Adds server-managed created/updated timestamps.

    Defaults come from the database rather than the application so rows written by migrations,
    maintenance jobs, or manual intervention still carry correct timestamps.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
