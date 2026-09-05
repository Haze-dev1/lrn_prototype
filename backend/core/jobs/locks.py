"""Redis-backed distributed locking for scheduled jobs.

Scheduler containers may run as multiple replicas. Every scheduled job acquires a lock so a
logical job window executes exactly once, and releases it only if it still owns it.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from commons.redis_client import get_redis
from core import logger

logging = logger(__name__)

_LOCK_KEY_PREFIX = "lrn:joblock:"

# Releases the lock only when the stored token matches, so a job that overran its TTL cannot
# delete a lock a different worker has since acquired.
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""


@asynccontextmanager
async def job_lock(name: str, ttl_seconds: int) -> AsyncIterator[bool]:
    """
    Acquire a distributed lock for a named scheduled job.

    Yields False instead of raising when another worker holds the lock, so the losing replica
    skips the run quietly rather than failing. The TTL bounds how long a crashed worker can block
    the job, so it must exceed the job's expected runtime.

    Args:
        name: Stable logical job name, used as the lock key.
        ttl_seconds: Lock expiry in seconds; must exceed the job's expected runtime.

    Returns:
        AsyncIterator[bool]: True when the lock was acquired by this caller, otherwise False.
    """
    redis_client = get_redis()
    key = f"{_LOCK_KEY_PREFIX}{name}"
    token = str(uuid.uuid4())

    acquired = bool(await redis_client.set(key, token, nx=True, ex=ttl_seconds))
    if not acquired:
        logging.info(f"Skipping job '{name}', lock held by another worker")
        yield False
        return

    try:
        yield True
    finally:
        try:
            await redis_client.eval(_RELEASE_SCRIPT, 1, key, token)
        except Exception as error:
            logging.error(f"Error releasing job lock '{name}': {error}")
