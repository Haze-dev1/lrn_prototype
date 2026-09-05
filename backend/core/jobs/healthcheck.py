"""Container health check for the scheduler process.

Run as a module (``python -m core.jobs.healthcheck``); exits non-zero when the scheduler has not
published a recent heartbeat, which Docker reports as an unhealthy container.
"""

import asyncio
import sys

from commons.redis_client import close_redis_connection, get_redis
from core.jobs.scheduler import HEARTBEAT_KEY


async def _is_healthy() -> bool:
    """
    Report whether a current scheduler heartbeat exists in Redis.

    The heartbeat key carries a TTL, so its mere presence proves the scheduler ran recently; no
    timestamp comparison is needed.

    Returns:
        bool: True when the heartbeat key is present.
    """
    try:
        return await get_redis().exists(HEARTBEAT_KEY) == 1
    except Exception:
        return False
    finally:
        await close_redis_connection()


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(_is_healthy()) else 1)
