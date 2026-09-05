"""Short-lived per-user locks that serialise entitlement-gated writes.

Every free-tier limit is a check followed by a write: count what the user has used, then create
the session or the attempt. Between those two steps another request can run the same check, and
concurrent submissions therefore all observe the same pre-write count and all pass. Measured
against a limit of three practice sets, ten simultaneous requests created ten; against a daily
grading allowance of fifteen, twenty simultaneous answers were all accepted and all graded. Each
of those answers is a paid model call, so the gap is a spending control that does not hold.

The lock closes it by serialising a single user's gated writes. It is deliberately per user:
there is no contention between students, and the critical section is two queries long.

Distinct from ``core.jobs.locks``, which skips a run when a lock is held because a scheduled job
that another replica is already running should not run twice. Here a caller must not be dropped,
so this one waits briefly and then proceeds.
"""

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from commons.redis_client import get_redis
from core import logger

logging = logger(__name__)

_LOCK_KEY_PREFIX = "lrn:userlock:"

# Release only when the token still matches, so a caller that overran the TTL cannot delete a
# lock another request has since taken.
_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""

_POLL_SECONDS = 0.05


@asynccontextmanager
async def user_gate_lock(
    user_id: uuid.UUID, *, name: str, ttl_seconds: int = 10, wait_seconds: float = 3.0
) -> AsyncIterator[None]:
    """
    Serialise one user's entitlement-gated writes.

    Fails open, in both directions. If the lock cannot be acquired within ``wait_seconds`` the
    body runs anyway, and if Redis is unreachable the body runs anyway — the same posture as the
    rate limiter, and for the same reason: losing the counter store must degrade a spending
    control, never take away a student's ability to answer a question. The TTL bounds how long a
    crashed request can block the same user, so it must exceed the critical section by a wide
    margin while staying short enough not to strand a real person.

    Args:
        user_id: The user whose gated writes are being serialised.
        name: Logical gate name, so two different gates do not contend with each other.
        ttl_seconds: Lock expiry, bounding the effect of a crash inside the critical section.
        wait_seconds: How long to wait for a contended lock before proceeding regardless.

    Returns:
        AsyncIterator[None]: A context in which this user's gated write is serialised.
    """
    key = f"{_LOCK_KEY_PREFIX}{name}:{user_id}"
    token = str(uuid.uuid4())
    acquired = False

    try:
        redis_client = get_redis()
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while True:
            acquired = bool(await redis_client.set(key, token, nx=True, ex=ttl_seconds))
            if acquired or asyncio.get_running_loop().time() >= deadline:
                break
            await asyncio.sleep(_POLL_SECONDS)
        if not acquired:
            logging.warning(
                f"Proceeding without the '{name}' lock for user {user_id}: still held after "
                f"{wait_seconds}s"
            )
    except Exception as error:
        logging.error(f"Error acquiring the '{name}' lock for user {user_id}: {error}")

    try:
        yield
    finally:
        if acquired:
            try:
                await get_redis().eval(_RELEASE_SCRIPT, 1, key, token)
            except Exception as error:
                logging.error(f"Error releasing the '{name}' lock for user {user_id}: {error}")
