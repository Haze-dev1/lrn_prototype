"""Redis-backed request rate limiting.

Used on the endpoints where abuse has a direct cost: password guessing on login, account
enumeration on registration, and paid model calls on grading. Counters live in Redis because they
are ephemeral, shared across API replicas, and must not add write load to the primary database.
"""

from dataclasses import dataclass

from commons.redis_client import get_redis
from core import logger

logging = logger(__name__)

_KEY_PREFIX = "lrn:ratelimit:"


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a rate limit check."""

    allowed: bool
    remaining: int
    retry_after_seconds: int


async def check_rate_limit(
    *, bucket: str, identifier: str, limit: int, window_seconds: int
) -> RateLimitResult:
    """
    Count one request against a fixed window and report whether it is allowed.

    Uses a fixed window rather than a sliding log: it costs two Redis commands and a single
    integer per key, which matters because a limiter that is expensive under load becomes its own
    denial of service. The tradeoff is that a burst can straddle a window boundary and briefly
    exceed the nominal rate, which is acceptable for abuse control.

    Fails open. If Redis is unreachable the request is allowed and the failure is logged, because
    losing the counter store must not lock every user out of signing in.

    Args:
        bucket: Logical limit name, for example 'login' or 'register'.
        identifier: What is being limited — a client IP, or an account identifier.
        limit: Maximum requests permitted per window.
        window_seconds: Window length in seconds.

    Returns:
        RateLimitResult: Whether the request is allowed, and when to retry if not.
    """
    key = f"{_KEY_PREFIX}{bucket}:{identifier}"
    try:
        redis_client = get_redis()
        pipeline = redis_client.pipeline()
        pipeline.incr(key)
        pipeline.ttl(key)
        count, ttl = await pipeline.execute()

        if ttl < 0:
            # First request in this window, or a key that lost its expiry; (re)apply the window.
            await redis_client.expire(key, window_seconds)
            ttl = window_seconds

        if count > limit:
            logging.warning(f"Rate limit exceeded for bucket '{bucket}'")
            return RateLimitResult(allowed=False, remaining=0, retry_after_seconds=int(ttl))

        return RateLimitResult(
            allowed=True, remaining=max(limit - int(count), 0), retry_after_seconds=int(ttl)
        )
    except Exception as error:
        logging.error(f"Error in check_rate_limit for bucket '{bucket}': {error}")
        return RateLimitResult(allowed=True, remaining=limit, retry_after_seconds=0)


async def reset_rate_limit(*, bucket: str, identifier: str) -> None:
    """
    Clear a rate-limit counter.

    Called after a successful login so a user who mistyped their password several times is not
    still penalised once they get it right.

    Args:
        bucket: Logical limit name.
        identifier: The limited identifier.
    """
    try:
        await get_redis().delete(f"{_KEY_PREFIX}{bucket}:{identifier}")
    except Exception as error:
        logging.error(f"Error in reset_rate_limit for bucket '{bucket}': {error}")
