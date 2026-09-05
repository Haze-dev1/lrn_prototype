"""Async database engine, session factory, and connectivity check.

The CRUD layer owns database access through ``session()``; routes and controllers never receive a
session parameter, per Eigi backend standards.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core import logger
from core.config.settings import settings

logging = logger(__name__)

_engine: AsyncEngine = create_async_engine(
    str(settings.DATABASE_URL),
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_timeout=settings.DATABASE_POOL_TIMEOUT,
    pool_pre_ping=True,
    echo=False,
)

_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=_engine, expire_on_commit=False, autoflush=False
)


def get_engine() -> AsyncEngine:
    """
    Return the process-wide async SQLAlchemy engine.

    Exposed for migrations, health checks, and shutdown; application code should use ``session()``.

    Returns:
        AsyncEngine: The shared async engine.
    """
    return _engine


@asynccontextmanager
async def session() -> AsyncIterator[AsyncSession]:
    """
    Provide a transactional async database session.

    Commits when the block exits cleanly and rolls back on any exception, so a failed CRUD call
    can never leave a half-applied transaction open on a pooled connection.

    Returns:
        AsyncIterator[AsyncSession]: Context-managed session bound to the shared engine.

    Raises:
        Exception: Re-raises any exception from the wrapped block after rolling back.
    """
    async with _session_factory() as db_session:
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise


async def check_database_connection() -> bool:
    """
    Verify the database is reachable and accepting queries.

    Runs a trivial statement rather than only opening a socket, so a database that accepts
    connections but cannot serve queries is reported as unhealthy.

    Returns:
        bool: True when the query succeeds, False otherwise.
    """
    try:
        async with _engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception as error:
        logging.error(f"Error in check_database_connection: {error}")
        return False


async def close_database_connection() -> None:
    """
    Dispose of the engine and close pooled database connections.

    Called during application shutdown so containers stop without leaking server-side sessions.
    """
    logging.info("Executing close_database_connection")
    await _engine.dispose()
