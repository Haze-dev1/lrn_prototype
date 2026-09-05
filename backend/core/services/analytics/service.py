"""Recording product events.

Two guarantees, and every design choice here serves one of them.

**Analytics can never break the product.** ``track`` returns immediately, dispatches the send as a
background task, and swallows everything. A student's answer submission does not wait on a
telemetry endpoint, and a telemetry outage cannot fail a request.

**Raw student content never leaves this process.** Properties pass through an allowlist before
they reach a provider: unknown keys are dropped, long strings are dropped, and nested structures
are dropped. That is enforced here, once, rather than trusted to each of the twenty call sites —
because the call site that forgets is the one that leaks.
"""

import asyncio
import uuid
from typing import Any

from core import logger
from core.services.analytics.events import MAX_PROPERTY_LENGTH, SAFE_PROPERTY_KEYS
from core.services.analytics.provider import AnalyticsProvider, get_analytics_provider

logging = logger(__name__)

# Strong references to in-flight dispatches. Without this the event loop is the only holder of the
# task and it can be garbage collected mid-send, which drops events non-deterministically under
# load — the exact conditions where the data matters most.
_in_flight: set[asyncio.Task[None]] = set()

#: Identifier used when there is no signed-in user, for landing views and anonymous pricing hits.
ANONYMOUS_ID = "anonymous"


def sanitise(properties: dict[str, Any] | None) -> dict[str, Any]:
    """
    Reduce event properties to safe, declared scalars.

    Drops anything not in ``SAFE_PROPERTY_KEYS``, anything that is not a scalar, and any string
    long enough to be prose rather than a label. The length rule is the backstop: it means that
    even a future property named from the allowlist cannot carry an answer, because an answer is
    never a hundred and twenty characters.

    Args:
        properties: Raw properties from a call site.

    Returns:
        dict[str, Any]: Properties safe to send.
    """
    if not properties:
        return {}

    safe: dict[str, Any] = {}
    for key, value in properties.items():
        if key not in SAFE_PROPERTY_KEYS:
            logging.debug(f"Dropped undeclared analytics property {key!r}")
            continue
        if isinstance(value, bool | int | float) or value is None:
            safe[key] = value
        elif isinstance(value, uuid.UUID):
            safe[key] = str(value)
        elif isinstance(value, str):
            if len(value) > MAX_PROPERTY_LENGTH:
                logging.warning(f"Dropped over-long analytics property {key!r}")
                continue
            safe[key] = value
        else:
            # Lists and dicts are dropped rather than serialised: a nested structure is where
            # free text hides from a key-level allowlist.
            logging.debug(f"Dropped non-scalar analytics property {key!r}")
    return safe


class AnalyticsService:
    """Sanitises and records product events."""

    def __init__(self, provider: AnalyticsProvider | None = None) -> None:
        """
        Initialise the service with a provider.

        Args:
            provider: Provider to use; defaults to the configured one, which may be None when
                analytics is switched off.
        """
        self.provider = provider if provider is not None else get_analytics_provider()

    async def record(
        self,
        *,
        event: str,
        user_id: uuid.UUID | str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """
        Record one event, waiting for it to be sent.

        The awaited form. Used by scheduled jobs, which have no request to hold open, and by tests,
        which need the send to have happened before they assert on it.

        Args:
            event: Event name, from ``AnalyticsEvent``.
            user_id: The actor, or None for an anonymous one.
            properties: Raw properties; sanitised before dispatch.
        """
        if self.provider is None:
            return
        try:
            await self.provider.capture(
                event=str(event),
                distinct_id=str(user_id) if user_id else ANONYMOUS_ID,
                properties=sanitise(properties),
            )
        except Exception as error:
            logging.warning(f"Could not record analytics event {event}: {error}")

    def track(
        self,
        *,
        event: str,
        user_id: uuid.UUID | str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """
        Record one event without waiting for it.

        The form used from request handling. Dispatches onto the running loop and returns, so no
        student ever waits on a telemetry endpoint. Outside a running loop — a synchronous script,
        an import-time call — it does nothing rather than starting one.

        Args:
            event: Event name, from ``AnalyticsEvent``.
            user_id: The actor, or None for an anonymous one.
            properties: Raw properties; sanitised before dispatch.
        """
        if self.provider is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logging.debug(f"No running loop; analytics event {event} not dispatched")
            return

        task = loop.create_task(self.record(event=event, user_id=user_id, properties=properties))
        _in_flight.add(task)
        task.add_done_callback(_in_flight.discard)


#: Process-wide instance. Building one per call would rebuild the provider on every event.
analytics = AnalyticsService()


def track(
    *,
    event: str,
    user_id: uuid.UUID | str | None = None,
    properties: dict[str, Any] | None = None,
) -> None:
    """
    Record one event without waiting for it.

    The call-site convenience over the shared service, so a controller records an event in one
    line and never has to think about instantiation or awaiting.

    Args:
        event: Event name, from ``AnalyticsEvent``.
        user_id: The actor, or None for an anonymous one.
        properties: Raw properties; sanitised before dispatch.
    """
    analytics.track(event=event, user_id=user_id, properties=properties)
