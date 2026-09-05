"""The PostHog adapter — the only module that knows where analytics actually goes.

PostHog's capture endpoint is a single unauthenticated JSON POST carrying the project's public
write key, so this uses ``httpx`` directly rather than adding an SDK whose main feature is a
background batching thread this application does not need: the caller already dispatches without
waiting.
"""

from datetime import UTC, datetime
from typing import Any

import httpx

from core import logger
from core.config.settings import settings
from core.services.analytics.provider import AnalyticsProvider

logging = logger(__name__)


class PostHogProvider(AnalyticsProvider):
    """Sends events to PostHog's capture endpoint."""

    name = "posthog"

    async def capture(self, *, event: str, distinct_id: str, properties: dict[str, Any]) -> None:
        """
        Send one event to PostHog.

        Swallows every failure. A telemetry endpoint being unreachable is not a fault worth
        surfacing anywhere near a student's request, and raising here would push that decision on
        to every call site.

        Args:
            event: Event name.
            distinct_id: Stable identifier for the actor.
            properties: Sanitised scalar properties.
        """
        try:
            async with httpx.AsyncClient(
                base_url=settings.POSTHOG_HOST, timeout=settings.ANALYTICS_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(
                    "/capture/",
                    json={
                        "api_key": settings.POSTHOG_API_KEY,
                        "event": event,
                        "distinct_id": distinct_id,
                        "properties": properties,
                        "timestamp": datetime.now(UTC).isoformat(),
                    },
                )
            if response.status_code >= 400:
                logging.warning(
                    f"PostHog rejected event {event} with {response.status_code}: "
                    f"{response.text[:200]}"
                )
        except Exception as error:
            logging.warning(f"Could not record analytics event {event}: {error}")
