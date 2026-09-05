"""Shared pytest fixtures and test environment configuration.

Test-only environment values are set before any application module is imported, so importing
settings during collection can never pick up a developer's real credentials or point tests at a
development database.
"""

import os

os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://lrn:lrn@localhost:5432/lrn_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
os.environ.setdefault("JWT_SECRET", "test-secret-value-that-is-at-least-32-chars-long")
os.environ.setdefault("GRADING_PROVIDER", "fake")

# Credentials for third-party integrations are cleared outright rather than defaulted. `make
# test-api` sources the developer's `.env` to find the database credentials, which also exports
# everything else in it — so a developer who has configured Google sign-in locally would flip
# these endpoints from "not configured" to "configured" and fail tests that assert the
# unconfigured behaviour. A suite whose result depends on the machine it runs on is not a suite.
# A test that needs one of these sets it explicitly through settings.
for _integration_credential in (
    "GOOGLE_CLIENT_ID",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "STRIPE_SECRET_KEY",
):
    os.environ.pop(_integration_credential, None)

import socket  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402
from pathlib import Path  # noqa: E402
from urllib.parse import urlparse  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from core.apis.api import app  # noqa: E402
from core.config.settings import settings  # noqa: E402
from core.database.database import get_engine, session  # noqa: E402

# Seeded reference data survives truncation: it is created by migration, and every question and
# skill score depends on it existing.
PRESERVED_TABLES = {"alembic_version", "categories"}


def _tcp_reachable(url: str, default_port: int) -> bool:
    """
    Report whether a service accepts TCP connections at a URL's host and port.

    Deliberately synchronous. An async probe at collection time would bind the application's
    process-wide connection pools to an event loop that pytest then closes.

    Args:
        url: Connection URL to parse.
        default_port: Port to assume when the URL omits one.

    Returns:
        bool: True when a TCP connection succeeds.
    """
    parsed = urlparse(url)
    try:
        with socket.create_connection(
            (parsed.hostname or "localhost", parsed.port or default_port), timeout=1
        ):
            return True
    except OSError:
        return False


def database_reachable() -> bool:
    """
    Report whether the configured test database server is reachable.

    Returns:
        bool: True when PostgreSQL accepts connections.
    """
    return _tcp_reachable(str(settings.DATABASE_URL), 5432)


def redis_reachable() -> bool:
    """
    Report whether the configured Redis server is reachable.

    Returns:
        bool: True when Redis accepts connections.
    """
    return _tcp_reachable(str(settings.REDIS_URL), 6379)


requires_database = pytest.mark.skipif(
    not database_reachable(),
    reason="PostgreSQL is not reachable; start the stack with `make up` to run database tests",
)


@pytest.fixture(scope="session")
async def migrated_database() -> AsyncIterator[None]:
    """
    Create the test database and bring it to the current migration head.

    Applies the real Alembic migrations rather than ``Base.metadata.create_all``, so the tests run
    against the schema a deployment would actually get — including the CHECK constraints and
    partial indexes that ``create_all`` would reproduce but a broken migration would not.

    Returns:
        AsyncIterator[None]: Fixture scope covering the whole test session.
    """
    await _create_database_if_missing()

    from alembic import command
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parent.parent
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    # Alembic's runner is synchronous and opens its own connection, so it is run off the event
    # loop to avoid nesting a second asyncio.run inside the test loop.
    import asyncio

    await asyncio.to_thread(command.upgrade, config, "head")
    yield
    await get_engine().dispose()


async def _create_database_if_missing() -> None:
    """
    Create the test database when it does not already exist.

    Connects to the server's default database because ``CREATE DATABASE`` cannot run inside a
    transaction against the database being created.
    """
    import psycopg

    url = urlparse(str(settings.DATABASE_URL).replace("postgresql+psycopg", "postgresql"))
    database_name = (url.path or "/lrn_test").lstrip("/")
    admin_dsn = url._replace(path="/postgres").geturl()

    async with await psycopg.AsyncConnection.connect(admin_dsn, autocommit=True) as connection:
        exists = await (
            await connection.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s", (database_name,)
            )
        ).fetchone()
        if not exists:
            await connection.execute(f'CREATE DATABASE "{database_name}"')


@pytest.fixture(autouse=True)
async def clean_database(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """
    Reset per-test state: truncate application tables and clear rate-limit counters.

    Rate-limit counters live in Redis and are keyed by client address. Under the in-process ASGI
    transport every test presents as the same client, so without this the suite exhausts the
    registration budget partway through and later tests fail with 429 for reasons that have
    nothing to do with what they assert.

    Only runs for tests that need the database, so pure unit tests stay fast and require no
    infrastructure. Seeded reference data is preserved.

    Returns:
        AsyncIterator[None]: Fixture scope covering one test.
    """
    if "migrated_database" not in request.fixturenames:
        yield
        return

    if redis_reachable():
        from commons.redis_client import get_redis

        redis_client = get_redis()
        keys = [key async for key in redis_client.scan_iter(match="lrn:ratelimit:*")]
        if keys:
            await redis_client.delete(*keys)

    async with session() as db:
        result = await db.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        )
        tables = [row[0] for row in result.all() if row[0] not in PRESERVED_TABLES]
        if tables:
            quoted = ", ".join(f'public."{name}"' for name in tables)
            # RESTART IDENTITY CASCADE clears dependent rows in one statement, so tests do not
            # have to delete in foreign-key order.
            await db.execute(text(f"TRUNCATE {quoted} RESTART IDENTITY CASCADE"))
    yield


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """
    Provide an HTTP client bound directly to the ASGI application.

    Requests are dispatched in-process, so tests exercise real routing, validation and error
    handling without binding a port or running a server.

    Returns:
        AsyncIterator[AsyncClient]: Client wired to the application via ASGI transport.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
