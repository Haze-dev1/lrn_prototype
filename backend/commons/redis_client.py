"""Shared async Redis client for ephemeral state and coordination.

Redis holds rate-limit counters, idempotency keys, scheduler locks, and short-lived cache entries.
It is never the source of truth for product data.
"""

import redis.asyncio as redis

from core import logger
from core.config.settings import settings

logging = logger(__name__)

_client: redis.Redis = redis.from_url(
    str(settings.REDIS_URL),
    encoding="utf-8",
    decode_responses=True,
    health_check_interval=30,
)


def get_redis() -> redis.Redis:
    """
    Return the process-wide async Redis client.

    The client manages its own connection pool, so it is created once and shared rather than
    reconnected per call.

    Returns:
        redis.Redis: Shared async Redis client.
    """
    return _client


async def check_redis_connection() -> bool:
    """
    Verify Redis is reachable.

    Issues a PING so an unreachable or unauthenticated Redis is reported as unhealthy.

    Returns:
        bool: True when the ping succeeds, False otherwise.
    """
    try:
        return bool(await _client.ping())
    except Exception as error:
        logging.error(f"Error in check_redis_connection: {error}")
        return False


async def close_redis_connection() -> None:
    """
    Close the Redis client and release pooled connections.

    Called during application shutdown so containers stop cleanly.
    """
    logging.info("Executing close_redis_connection")
    await _client.aclose()
