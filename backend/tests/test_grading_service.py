"""Tests for the grading flow against a real database.

The invariant under test throughout is that an answer is never lost to an AI failure. Every
failure mode a provider can produce — a timeout, a transport error, prose instead of JSON, a
score of 900, an invented concept key — is driven here, and in every case the answer must survive
with no score attached and a state the retry sweep can reclaim.
"""

import json
from decimal import Decimal
from typing import Any

import pytest

from core.constants.enums import Band, GradingStatus, ValidationStatus
from core.cruds.attempt_crud import CRUDAttempt, CRUDGradeEvent
from core.services.ai.grading_service import GradingService
from core.services.ai.provider import GradingProvider
from core.services.ai.types import GradingError, GradingFailureKind, ProviderCall
from tests.conftest import requires_database
from tests.factories import (
    make_attempt,
    make_gradeable_question,
    make_question,
    make_question_version,
    make_session,
    make_user,
)

pytestmark = [requires_database, pytest.mark.usefixtures("migrated_database")]


@pytest.fixture(autouse=True)
def _no_retry_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Remove the immediate-retry backoff for every test in this module.

    No test here asserts on how long a retry waits — only on how many happen and what state the
    attempt ends in — so the real backoff is pure wall-clock cost. Three failure tests each slept
    three seconds through it before this.

    Args:
        monkeypatch: Pytest patching fixture.
    """
    monkeypatch.setattr("core.services.ai.grading_service.RETRY_BACKOFF_SECONDS", 0.0)


class StubProvider(GradingProvider):
    """A provider whose response each test dictates."""

    name = "stub"

    def __init__(self, *, content: str | None = None, error: GradingError | None = None) -> None:
        """
        Configure the response this provider will produce.

        Args:
            content: Raw content to return.
            error: Failure to raise instead of returning.
        """
        self._content = content
        self._error = error
        self.calls = 0

    @property
    def model(self) -> str:
        """
        Return a fixed model identifier.

        Returns:
            str: The stub model name.
        """
        return "stub/model-1"

    async def complete(
        self, *, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> ProviderCall:
        """
        Return the configured response, or raise the configured failure.

        Args:
            system_prompt: Ignored.
            user_prompt: Recorded for assertions about prompt content.
            json_schema: Ignored.

        Returns:
            ProviderCall: The configured content with synthetic accounting.

        Raises:
            GradingError: When the stub was configured to fail.
        """
        self.calls += 1
        self.last_user_prompt = user_prompt
        if self._error is not None:
            raise self._error
        return ProviderCall(
            content=self._content or "",
            provider=self.name,
            model=self.model,
            model_version="stub/model-1-20260101",
            request_id="stub-request-1",
            input_tokens=1200,
            output_tokens=180,
            cost=Decimal("0.000431"),
            latency_ms=842,
            raw_response={"stub": True},
        )


def grade_json(**overrides: Any) -> str:
    """
    Build a valid model grade response.

    Args:
        **overrides: Fields to override on the valid default.

    Returns:
        str: The response serialised as JSON.
    """
    payload: dict[str, Any] = {
        "score": 78,
        "band": "developing",
        "feedback": "You covered the net debt bridge but did not address cash equivalents.",
        "concepts_hit": ["net_debt"],
        "concepts_missed": ["cash"],
        "mistake_flags": [],
    }
    payload.update(overrides)
    return json.dumps(payload)


async def pending_attempt(**attempt_overrides: Any):
    """
    Create a user, session, gradeable question, and an ungraded attempt against it.

    Args:
        **attempt_overrides: Fields to override on the attempt.

    Returns:
        Attempt: The pending attempt.
    """
    user = await make_user()
    question, version = await make_gradeable_question()
    session_row = await make_session(
        user_id=user.id,
        questions=[{"position": 0, "question_id": question.id, "question_version_id": version.id}],
    )
    return await make_attempt(
        user_id=user.id,
        session_id=session_row.id,
        question_id=question.id,
        question_version_id=version.id,
        **attempt_overrides,
    )


class TestSuccessfulGrading:
    """The path where the provider behaves."""

    async def test_a_valid_response_grades_the_attempt(self) -> None:
        """The attempt reaches GRADED carrying its score, band and evidence."""
        attempt = await pending_attempt()

        graded = await GradingService(provider=StubProvider(content=grade_json())).grade_attempt(
            attempt_id=attempt.id
        )

        assert graded is not None
        assert graded.grading_status == GradingStatus.GRADED
        assert graded.score == 78
        assert graded.band == Band.DEVELOPING
        assert graded.concepts_hit == ["net_debt"]
        assert graded.graded_at is not None

    async def test_the_audit_trail_records_the_call(self) -> None:
        """Provider, model, versions, usage, latency and cost are all captured.

        Without these a grading regression cannot be attributed and a disputed grade cannot be
        investigated.
        """
        attempt = await pending_attempt()

        await GradingService(provider=StubProvider(content=grade_json())).grade_attempt(
            attempt_id=attempt.id
        )
        events = await CRUDGradeEvent().list_for_attempt(attempt_id=attempt.id)

        assert len(events) == 1
        event = events[0]
        assert event.provider == "stub"
        assert event.model == "stub/model-1"
        assert event.model_version == "stub/model-1-20260101"
        assert event.provider_request_id == "stub-request-1"
        assert event.prompt_version.startswith("grade.")
        assert event.input_tokens == 1200
        assert event.output_tokens == 180
        assert event.latency_ms == 842
        assert event.estimated_cost == Decimal("0.000431")
        assert event.validation_status == ValidationStatus.VALID

    async def test_the_audit_records_the_rubric_version_that_graded(self) -> None:
        """A grade is only attributable if it names the exact rubric behind it."""
        user = await make_user()
        question = await make_question()
        await make_question_version(question_id=question.id)
        second = await make_question_version(question_id=question.id)
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": second.id}
            ],
        )
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=second.id,
        )

        await GradingService(provider=StubProvider(content=grade_json())).grade_attempt(
            attempt_id=attempt.id
        )
        events = await CRUDGradeEvent().list_for_attempt(attempt_id=attempt.id)

        assert events[0].rubric_version == second.version

    async def test_the_student_answer_reaches_the_prompt_fenced(self) -> None:
        """The answer is present, and inside the delimiter."""
        attempt = await pending_attempt(answer="Enterprise value less net debt gives equity value.")
        provider = StubProvider(content=grade_json())

        await GradingService(provider=provider).grade_attempt(attempt_id=attempt.id)

        assert "Enterprise value less net debt" in provider.last_user_prompt
        assert "STUDENT_SUBMISSION_" in provider.last_user_prompt

    async def test_quality_signals_are_recorded_on_a_successful_grade(self) -> None:
        """A drifting model is visible before it becomes a correctness problem."""
        attempt = await pending_attempt()
        content = grade_json(score=30, band="strong", concepts_hit=["net_debt", "invented_key"])

        await GradingService(provider=StubProvider(content=content)).grade_attempt(
            attempt_id=attempt.id
        )
        events = await CRUDGradeEvent().list_for_attempt(attempt_id=attempt.id)

        assert events[0].validation_status == ValidationStatus.VALID
        assert "band disagreed" in (events[0].error_message or "")
        assert "dropped 1" in (events[0].error_message or "")


class TestFakeProviderEndToEnd:
    """The default provider must survive the same validation as a real one.

    Every other test here drives a stub whose keys are written by hand, which cannot catch a
    provider that reports keys the rubric does not declare. That gap hid a real defect: the fake
    provider's parser included ":" in its key character class, so it reported "net_debt:" and
    validation correctly dropped every key — producing scores of 100 with no concepts hit for
    anyone running the default configuration locally.
    """

    async def test_the_fake_provider_reports_keys_the_rubric_declares(self) -> None:
        """No key is dropped when grading through the real prompt and validation path."""
        from core.services.ai.fake_provider import FakeGradingProvider

        attempt = await pending_attempt(
            answer=(
                "Subtract net debt: take out total debt and add back cash and equivalents "
                "to bridge from enterprise value to equity value."
            )
        )
        service = GradingService(provider=FakeGradingProvider())

        graded = await service.grade_attempt(attempt_id=attempt.id)

        assert graded is not None
        assert graded.grading_status == GradingStatus.GRADED
        reported = set(graded.concepts_hit or []) | set(graded.concepts_missed or [])
        assert reported, "the provider reported no usable concept keys at all"

        events = await CRUDGradeEvent().list_for_attempt(attempt_id=attempt.id)
        assert events[0].error_message is None, (
            f"keys were dropped during validation: {events[0].error_message}"
        )

    async def test_a_scored_answer_names_the_concepts_behind_the_score(self) -> None:
        """A score of 100 with no concepts hit is arithmetically impossible.

        This is the shape the bug took in production data, so it is asserted directly.
        """
        from core.services.ai.fake_provider import FakeGradingProvider

        attempt = await pending_attempt(
            answer=(
                "Subtract net debt from enterprise value: total debt less cash and equivalents, "
                "adjusting for the cash the acquirer receives at closing."
            )
        )

        graded = await GradingService(provider=FakeGradingProvider()).grade_attempt(
            attempt_id=attempt.id
        )

        assert graded is not None
        assert graded.score is not None
        if graded.score > 0:
            assert graded.concepts_hit, "a positive score must name the concepts behind it"

    async def test_a_weak_answer_names_what_it_missed(self) -> None:
        """Missed concepts are what make the feedback actionable rather than a verdict."""
        from core.services.ai.fake_provider import FakeGradingProvider

        attempt = await pending_attempt(answer="I am not sure how to approach this question.")

        graded = await GradingService(provider=FakeGradingProvider()).grade_attempt(
            attempt_id=attempt.id
        )

        assert graded is not None
        assert graded.concepts_missed, "a weak answer must report the concepts it did not cover"


class TestGradingFailures:
    """An answer must survive every way a provider can fail."""

    @pytest.mark.parametrize(
        ("kind", "expected_status"),
        [
            (GradingFailureKind.TIMEOUT, ValidationStatus.TIMEOUT),
            (GradingFailureKind.PROVIDER_ERROR, ValidationStatus.PROVIDER_ERROR),
        ],
    )
    async def test_a_transient_failure_leaves_the_answer_intact(
        self, kind: GradingFailureKind, expected_status: ValidationStatus
    ) -> None:
        """The answer is preserved with no score, and left for the retry sweep."""
        attempt = await pending_attempt()
        provider = StubProvider(error=GradingError(kind, "provider unavailable"))

        result = await GradingService(provider=provider).grade_attempt(attempt_id=attempt.id)

        assert result is not None
        assert result.answer == attempt.answer
        assert result.score is None
        assert result.band is None
        assert result.grading_status == GradingStatus.PENDING

        events = await CRUDGradeEvent().list_for_attempt(attempt_id=attempt.id)
        assert events[0].validation_status == expected_status

    async def test_a_failure_never_writes_a_score_of_zero(self) -> None:
        """The single most important guarantee in the grading path.

        A grading failure and a genuinely bad answer must never be indistinguishable. The
        database rejects a non-graded attempt carrying a score, so this is enforced by the schema
        as well as by the code.
        """
        attempt = await pending_attempt()
        provider = StubProvider(error=GradingError(GradingFailureKind.TIMEOUT, "timed out"))

        result = await GradingService(provider=provider).grade_attempt(attempt_id=attempt.id)

        assert result is not None
        assert result.score is None
        assert result.score != 0

    async def test_prose_instead_of_json_is_recorded_as_a_schema_failure(self) -> None:
        """A model that ignores the schema fails cleanly rather than corrupting the grade."""
        attempt = await pending_attempt()

        result = await GradingService(
            provider=StubProvider(content="I think this answer was pretty good overall.")
        ).grade_attempt(attempt_id=attempt.id)

        assert result is not None
        assert result.score is None
        assert result.grading_status == GradingStatus.PENDING
        events = await CRUDGradeEvent().list_for_attempt(attempt_id=attempt.id)
        assert events[0].validation_status == ValidationStatus.INVALID_SCHEMA

    async def test_an_out_of_range_score_is_recorded_as_a_values_failure(self) -> None:
        """Well-formed JSON with impossible values is still not a grade."""
        attempt = await pending_attempt()

        await GradingService(provider=StubProvider(content=grade_json(score=900))).grade_attempt(
            attempt_id=attempt.id
        )
        events = await CRUDGradeEvent().list_for_attempt(attempt_id=attempt.id)

        assert events[0].validation_status == ValidationStatus.INVALID_VALUES

    async def test_a_failed_call_still_records_its_accounting(self) -> None:
        """A malformed response is the case most worth investigating.

        Discarding the cost and latency of the call that produced it would hide exactly that.
        """
        attempt = await pending_attempt()

        await GradingService(provider=StubProvider(content="not json")).grade_attempt(
            attempt_id=attempt.id
        )
        events = await CRUDGradeEvent().list_for_attempt(attempt_id=attempt.id)

        assert events[0].latency_ms == 842
        assert events[0].estimated_cost == Decimal("0.000431")
        assert events[0].raw_response == {"stub": True}

    async def test_a_non_retryable_failure_fails_the_attempt_immediately(self) -> None:
        """A misconfiguration will fail identically forever, so it does not consume the sweep."""
        attempt = await pending_attempt()
        provider = StubProvider(error=GradingError(GradingFailureKind.NOT_CONFIGURED, "no api key"))

        result = await GradingService(provider=provider).grade_attempt(attempt_id=attempt.id)

        assert result is not None
        assert result.grading_status == GradingStatus.FAILED
        assert result.score is None

    async def test_unreachable_question_content_fails_without_retrying(self) -> None:
        """An attempt that cannot be graded at all stops burning the retry budget.

        The foreign keys are ON DELETE RESTRICT, so a version cannot actually be deleted out from
        under an attempt — this drives the guard directly rather than pretending the database
        allows the state. The guard is still worth having: it is the difference between a clear
        terminal failure and an AttributeError inside a background task.
        """
        attempt = await pending_attempt()
        service = GradingService(provider=StubProvider(content=grade_json()))

        async def missing_version(**_: Any) -> None:
            return None

        service.CRUDQuestionVersion.get_by_id = missing_version  # type: ignore[method-assign]

        result = await service.grade_attempt(attempt_id=attempt.id)

        assert result is not None
        assert result.score is None
        assert result.grading_status == GradingStatus.FAILED
        events = await CRUDGradeEvent().list_for_attempt(attempt_id=attempt.id)
        assert events[0].validation_status == ValidationStatus.PROVIDER_ERROR

    async def test_grading_a_missing_attempt_returns_none(self) -> None:
        """A deleted attempt is not an error for a background task."""
        import uuid

        result = await GradingService(provider=StubProvider(content=grade_json())).grade_attempt(
            attempt_id=uuid.uuid4()
        )

        assert result is None


class TestRetryBehaviour:
    """Immediate retries, and the scheduled sweep behind them."""

    async def test_a_transient_failure_is_retried_immediately(self, monkeypatch) -> None:
        """A single blip should not make a student wait for the next sweep."""
        monkeypatch.setattr("core.services.ai.grading_service.RETRY_BACKOFF_SECONDS", 0.0)
        attempt = await pending_attempt()
        provider = StubProvider(error=GradingError(GradingFailureKind.TIMEOUT, "timed out"))

        await GradingService(provider=provider).grade_attempt(attempt_id=attempt.id)

        # One initial call plus GRADING_MAX_RETRIES further attempts.
        assert provider.calls == 3

    async def test_a_non_retryable_failure_is_not_retried(self, monkeypatch) -> None:
        """Retrying a misconfiguration wastes money and delays the answer."""
        monkeypatch.setattr("core.services.ai.grading_service.RETRY_BACKOFF_SECONDS", 0.0)
        attempt = await pending_attempt()
        provider = StubProvider(error=GradingError(GradingFailureKind.NOT_CONFIGURED, "no api key"))

        await GradingService(provider=provider).grade_attempt(attempt_id=attempt.id)

        assert provider.calls == 1

    async def test_an_already_graded_attempt_is_not_regraded(self) -> None:
        """A sweep racing the background task must not rewrite a grade already shown."""
        attempt = await pending_attempt()
        await GradingService(provider=StubProvider(content=grade_json())).grade_attempt(
            attempt_id=attempt.id
        )

        provider = StubProvider(content=grade_json(score=10))
        result = await GradingService(provider=provider).grade_attempt(attempt_id=attempt.id)

        assert provider.calls == 0
        assert result is not None
        assert result.score == 78

    async def test_the_sweep_ignores_attempts_that_are_too_recent(self) -> None:
        """Otherwise it would grade an answer the submitting request is still grading."""
        await pending_attempt()

        summary = await GradingService(
            provider=StubProvider(content=grade_json())
        ).retry_unresolved()

        assert summary["examined"] == 0

    async def test_the_sweep_grades_a_stranded_attempt(self, monkeypatch) -> None:
        """The durability guarantee: a crash between persisting and grading loses nothing."""
        monkeypatch.setattr("core.config.settings.settings.GRADING_RETRY_AFTER_SECONDS", 0)
        attempt = await pending_attempt()

        summary = await GradingService(
            provider=StubProvider(content=grade_json())
        ).retry_unresolved()
        regraded = await CRUDAttempt().get_by_id(attempt_id=attempt.id)

        assert summary["graded"] == 1
        assert regraded is not None
        assert regraded.grading_status == GradingStatus.GRADED

    async def test_the_sweep_abandons_an_attempt_that_keeps_failing(self, monkeypatch) -> None:
        """Spending is bounded, and the answer stays visible rather than being scored."""
        monkeypatch.setattr("core.config.settings.settings.GRADING_RETRY_AFTER_SECONDS", 0)
        monkeypatch.setattr("core.config.settings.settings.GRADING_MAX_LIFETIME_RETRIES", 2)
        attempt = await pending_attempt(retry_count=2)
        provider = StubProvider(content=grade_json())

        summary = await GradingService(provider=provider).retry_unresolved()
        abandoned = await CRUDAttempt().get_by_id(attempt_id=attempt.id)

        assert summary["abandoned"] == 1
        assert provider.calls == 0
        assert abandoned is not None
        assert abandoned.grading_status == GradingStatus.FAILED
        assert abandoned.score is None

    async def test_the_sweep_increments_the_retry_count(self, monkeypatch) -> None:
        """Retry spending is only bounded if the count actually moves."""
        monkeypatch.setattr("core.config.settings.settings.GRADING_RETRY_AFTER_SECONDS", 0)
        monkeypatch.setattr("core.services.ai.grading_service.RETRY_BACKOFF_SECONDS", 0.0)
        attempt = await pending_attempt()
        provider = StubProvider(error=GradingError(GradingFailureKind.TIMEOUT, "timed out"))

        await GradingService(provider=provider).retry_unresolved()
        retried = await CRUDAttempt().get_by_id(attempt_id=attempt.id)

        assert retried is not None
        assert retried.retry_count == 1
