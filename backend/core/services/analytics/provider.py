"""The analytics provider boundary.

Narrow on purpose: a provider takes an already-named, already-sanitised event and records it. It
does no filtering of its own, because the filtering is a product rule and must hold whichever
provider is configured — including the local one, so a developer can see exactly what production
would send.
"""

from abc import ABC, abstractmethod
from typing import Any

from core import logger
from core.config.settings import settings

logging = logger(__name__)


class AnalyticsProvider(ABC):
    """Records product events."""

    #: Stable identifier for the log line.
    name: str

    @abstractmethod
    async def capture(self, *, event: str, distinct_id: str, properties: dict[str, Any]) -> None:
        """
        Record one event.

        Must not raise. Analytics is an observation of the product, never a part of it, and an
        event that cannot be recorded is not a reason for a student's request to fail.

        Args:
            event: Event name.
            distinct_id: Stable identifier for the actor.
            properties: Sanitised scalar properties.
        """


def get_analytics_provider() -> AnalyticsProvider | None:
    """
    Build the analytics provider named by configuration.

    Returns None when analytics is switched off entirely, which is a supported deployment: a
    self-hosted installation with no third-party telemetry should not have to configure a
    destination it does not want.

    Returns:
        AnalyticsProvider | None: The configured provider, or None when disabled.
    """
    if settings.ANALYTICS_PROVIDER == "none":
        return None

    if settings.ANALYTICS_PROVIDER == "posthog" and settings.POSTHOG_API_KEY:
        from core.services.analytics.posthog_provider import PostHogProvider

        return PostHogProvider()

    if settings.ANALYTICS_PROVIDER == "posthog":
        logging.warning(
            "ANALYTICS_PROVIDER is 'posthog' but no API key is configured; logging instead"
        )

    from core.services.analytics.log_provider import LogAnalyticsProvider

    return LogAnalyticsProvider()
