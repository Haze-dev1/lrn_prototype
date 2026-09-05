"""Analytics: what gets recorded, and — more importantly — what cannot.

The product rule is that raw student answer content never reaches general analytics. A test that
only checks the happy path would pass forever while that rule quietly broke, so most of this file
is attempts to get answer text through the boundary by every route a careless call site might
take: an obvious key, a plausible-looking allowlisted key, a nested structure, a list.
"""

import uuid
from typing import Any

from httpx import AsyncClient

from core.services.analytics.events import (
    MAX_PROPERTY_LENGTH,
    PUBLIC_EVENTS,
    SAFE_PROPERTY_KEYS,
    AnalyticsEvent,
)
from core.services.analytics.provider import AnalyticsProvider
from core.services.analytics.service import ANONYMOUS_ID, AnalyticsService, sanitise

STUDENT_ANSWER = (
    "You bridge from enterprise value to equity value by subtracting net debt, which is total "
    "debt less cash and cash equivalents, and then adjusting for minority interest, preferred "
    "stock and any unconsolidated investments."
)


class RecordingProvider(AnalyticsProvider):
    """Captures what the service decided to send."""

    name = "recording"

    def __init__(self, *, fail: bool = False) -> None:
        """
        Initialise the recorder.

        Args:
            fail: Raise on capture, to prove a provider failure cannot escape.
        """
        self.captured: list[dict[str, Any]] = []
        self.fail = fail

    async def capture(self, *, event: str, distinct_id: str, properties: dict[str, Any]) -> None:
        """Record the call, or fail. See ``AnalyticsProvider``."""
        if self.fail:
            raise RuntimeError("analytics backend is down")
        self.captured.append({"event": event, "distinct_id": distinct_id, "properties": properties})


class TestPropertySanitising:
    """The allowlist, examined from the side an attacker or a careless caller would use."""

    def test_declared_scalars_pass_through(self) -> None:
        """The properties events actually carry are not disturbed."""
        clean = sanitise({"score": 82, "band": "strong", "category_slug": "valuation"})

        assert clean == {"score": 82, "band": "strong", "category_slug": "valuation"}

    def test_an_answer_field_is_dropped(self) -> None:
        """The obvious mistake: passing the answer straight through."""
        assert sanitise({"answer": STUDENT_ANSWER, "score": 70}) == {"score": 70}

    def test_every_content_bearing_name_is_undeclared(self) -> None:
        """None of the fields that carry student or rubric text may be sent, by construction."""
        forbidden = {
            "answer",
            "prompt",
            "feedback",
            "ideal_answer",
            "expected_concepts",
            "common_mistakes",
            "concepts_hit",
            "concepts_missed",
            "comment",
            "rubric",
            "email",
        }

        assert not (forbidden & SAFE_PROPERTY_KEYS)

    def test_a_long_string_is_dropped_even_under_a_declared_key(self) -> None:
        """The backstop. Even a permitted key cannot smuggle prose, because prose is long."""
        clean = sanitise({"reason": STUDENT_ANSWER, "score": 1})

        assert clean == {"score": 1}

    def test_a_string_at_the_limit_survives(self) -> None:
        """The rule bounds prose, not ordinary labels."""
        label = "x" * MAX_PROPERTY_LENGTH

        assert sanitise({"reason": label}) == {"reason": label}

    def test_nested_structures_are_dropped(self) -> None:
        """A dict or a list is where free text hides from a key-level allowlist."""
        clean = sanitise(
            {
                "score": 50,
                "band": {"nested": STUDENT_ANSWER},
                "category_slug": [STUDENT_ANSWER],
            }
        )

        assert clean == {"score": 50}

    def test_uuids_become_strings(self) -> None:
        """Identifiers are sent, and JSON has no UUID."""
        attempt_id = uuid.uuid4()

        assert sanitise({"attempt_id": attempt_id}) == {"attempt_id": str(attempt_id)}

    def test_none_and_booleans_survive(self) -> None:
        """A null property is meaningful — 'no category' is different from 'unset'."""
        assert sanitise({"category_slug": None, "is_paid": False}) == {
            "category_slug": None,
            "is_paid": False,
        }

    def test_empty_properties_are_fine(self) -> None:
        """An event with nothing attached is still an event."""
        assert sanitise(None) == {}


class TestRecording:
    """The service's own behaviour around the provider."""

    async def test_an_event_reaches_the_provider_sanitised(self) -> None:
        """The end-to-end shape: named event, actor, and only declared properties."""
        provider = RecordingProvider()
        user_id = uuid.uuid4()

        await AnalyticsService(provider=provider).record(
            event=AnalyticsEvent.GRADE_RECEIVED,
            user_id=user_id,
            properties={"score": 91, "answer": STUDENT_ANSWER},
        )

        assert provider.captured == [
            {
                "event": "grade_received",
                "distinct_id": str(user_id),
                "properties": {"score": 91},
            }
        ]

    async def test_an_anonymous_actor_gets_a_stable_identifier(self) -> None:
        """A landing view has no user, and must still be countable."""
        provider = RecordingProvider()

        await AnalyticsService(provider=provider).record(event=AnalyticsEvent.LANDING_VIEW)

        assert provider.captured[0]["distinct_id"] == ANONYMOUS_ID

    async def test_a_provider_failure_never_escapes(self) -> None:
        """Analytics is an observation of the product, never a part of it."""
        service = AnalyticsService(provider=RecordingProvider(fail=True))

        await service.record(event=AnalyticsEvent.ANSWER_SUBMITTED, user_id=uuid.uuid4())

    async def test_analytics_can_be_switched_off_entirely(self) -> None:
        """A deployment that wants no telemetry is a supported deployment."""
        service = AnalyticsService(provider=None)

        await service.record(event=AnalyticsEvent.LANDING_VIEW)
        service.track(event=AnalyticsEvent.LANDING_VIEW)

    async def test_track_dispatches_without_blocking(self) -> None:
        """The request-path form returns before the send completes, then completes."""
        import asyncio

        provider = RecordingProvider()
        service = AnalyticsService(provider=provider)

        service.track(event=AnalyticsEvent.REVIEW_OPENED, user_id=uuid.uuid4())
        assert provider.captured == []

        # Yield once so the dispatched task runs.
        await asyncio.sleep(0)
        assert len(provider.captured) == 1


class TestPublicEventEndpoint:
    """What a browser is allowed to assert."""

    async def test_a_public_event_is_accepted(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """Landing views only happen in a browser, so a browser has to report them."""
        response = await client.post("/v1/analytics/events", json={"event": "landing_view"})

        assert response.status_code == 202
        assert response.json()["status"] == "accepted"

    async def test_a_funnel_event_cannot_be_forged(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """The most important test here.

        ``checkout_completed`` is the number the product is measured on, and it is written only
        from a verified payment event. An anonymous POST must not be able to add one.
        """
        response = await client.post("/v1/analytics/events", json={"event": "checkout_completed"})

        assert response.status_code == 202
        assert response.json()["status"] == "ignored"

    def test_the_public_allowlist_stays_small(self) -> None:
        """A guard on the allowlist itself, so it cannot quietly grow into the funnel."""
        assert PUBLIC_EVENTS <= {AnalyticsEvent.LANDING_VIEW, AnalyticsEvent.PAYWALL_REACHED}

    async def test_the_endpoint_takes_no_properties(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """A property bag from an untrusted client is a free-text channel into analytics."""
        response = await client.post(
            "/v1/analytics/events",
            json={"event": "landing_view", "properties": {"answer": STUDENT_ANSWER}},
        )

        assert response.status_code == 202
        # Pydantic ignores the extra field rather than binding it; the schema has nowhere to put
        # it, which is the enforcement.
        from core.apis.schemas.requests.email_request import PublicEventRequest

        assert "properties" not in PublicEventRequest.model_fields


class TestRetentionWindows:
    """Return windows, which are ranges rather than exact days."""

    def test_windows_do_not_overlap_and_cover_the_gap(self) -> None:
        """Week two ends where week four begins, so no return is counted in both."""
        from core.services.analytics.retention_service import WINDOWS

        week_2, week_4 = WINDOWS
        assert week_2.max_days < week_4.min_days
        assert week_4.min_days == week_2.max_days + 1

    def test_a_window_is_a_range_not_a_day(self) -> None:
        """Activity is bursty: a student returning on day 15 has returned in week two."""
        from core.services.analytics.retention_service import WINDOWS

        week_2 = WINDOWS[0]
        assert week_2.min_days <= 15 <= week_2.max_days
