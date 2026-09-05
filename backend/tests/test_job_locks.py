"""Integration tests for Redis-backed scheduled job locking.

These run against a real Redis because the guarantee under test — that exactly one worker runs a
job — lives in Redis' atomic SET NX and a compare-and-delete Lua script. A mocked Redis would
assert the test's own assumptions rather than the behaviour that matters.
"""

import asyncio
import uuid

import pytest

from commons.redis_client import get_redis
from core.jobs.locks import job_lock
from tests.conftest import redis_reachable

pytestmark = pytest.mark.skipif(
    not redis_reachable(),
    reason="Redis is not reachable; start the stack with `make up` to run lock integration tests",
)


async def test_only_one_concurrent_worker_acquires_the_lock() -> None:
    """Concurrent workers contending for one job name yield exactly one lock holder."""
    job_name = f"test-exclusive-{uuid.uuid4()}"
    results: list[bool] = []

    async def worker() -> None:
        async with job_lock(job_name, ttl_seconds=10) as acquired:
            results.append(acquired)
            if acquired:
                await asyncio.sleep(0.2)

    await asyncio.gather(*(worker() for _ in range(8)))

    assert results.count(True) == 1
    assert results.count(False) == 7


async def test_lock_is_released_for_the_next_run() -> None:
    """A completed job releases its lock so the following scheduled run can acquire it."""
    job_name = f"test-release-{uuid.uuid4()}"

    async with job_lock(job_name, ttl_seconds=10) as first:
        assert first is True

    async with job_lock(job_name, ttl_seconds=10) as second:
        assert second is True


async def test_lock_is_released_when_the_job_raises() -> None:
    """A failing job must not leave its lock held until the TTL expires."""
    job_name = f"test-failure-{uuid.uuid4()}"

    with pytest.raises(RuntimeError):
        async with job_lock(job_name, ttl_seconds=30) as acquired:
            assert acquired is True
            raise RuntimeError("job failed")

    async with job_lock(job_name, ttl_seconds=10) as reacquired:
        assert reacquired is True


async def test_worker_does_not_delete_a_lock_it_no_longer_owns() -> None:
    """
    An overrunning worker must not release a lock a different worker has since acquired.

    Simulates TTL expiry by deleting the key mid-run and letting a second worker take the lock;
    when the first worker exits, the second worker's lock must survive.
    """
    job_name = f"test-token-{uuid.uuid4()}"
    redis_client = get_redis()
    key = f"lrn:joblock:{job_name}"

    async with job_lock(job_name, ttl_seconds=30) as first:
        assert first is True
        # Stand in for the first worker's lock expiring while it was still running.
        await redis_client.delete(key)
        await redis_client.set(key, "second-worker-token", ex=30)

    assert await redis_client.get(key) == "second-worker-token"
    await redis_client.delete(key)
