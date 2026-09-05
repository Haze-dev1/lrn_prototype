"""Runtime entrypoint for the LRN scheduler process.

Runs in its own container so scheduled work never competes with request handling for the API's
event loop, and so the scheduler can be scaled or restarted independently.
"""

import asyncio
import signal

from commons.redis_client import close_redis_connection
from core import logger
from core.config.settings import settings
from core.database.database import close_database_connection
from core.jobs.scheduler import build_scheduler

logging = logger(__name__)


async def run() -> None:
    """
    Start the scheduler and run until the process receives a termination signal.

    Waits on an event rather than sleeping in a loop so shutdown is immediate, and closes
    datastore connections on the way out so container stops are clean.
    """
    logging.info(f"Starting scheduler in {settings.ENVIRONMENT} environment")
    scheduler = build_scheduler()
    scheduler.start()

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        logging.info("Shutting down scheduler")
        scheduler.shutdown(wait=True)
        await close_database_connection()
        await close_redis_connection()


if __name__ == "__main__":
    asyncio.run(run())
