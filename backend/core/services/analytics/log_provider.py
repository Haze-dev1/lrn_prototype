"""The default analytics provider: writes events to the log and sends nothing.

What a fresh clone and the test suite get. It exercises the whole path — naming, sanitising,
dispatch — without a network call or an account, so the properties a developer sees locally are
exactly the ones production would send.
"""

from typing import Any

from core import logger
from core.services.analytics.provider import AnalyticsProvider

logging = logger(__name__)


class LogAnalyticsProvider(AnalyticsProvider):
    """Records events to the application log."""

    name = "log"

    async def capture(self, *, event: str, distinct_id: str, properties: dict[str, Any]) -> None:
        """
        Log one event instead of sending it.

        Args:
            event: Event name.
            distinct_id: Stable identifier for the actor.
            properties: Sanitised scalar properties.
        """
        logging.info(f"[analytics] {event} actor={distinct_id} {properties}")
