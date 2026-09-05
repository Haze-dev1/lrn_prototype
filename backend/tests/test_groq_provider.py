"""Tests for the Groq grading adapter.

The adapter is the only place the application knows a model vendor exists, so what is pinned here
is the translation in both directions: a grading request becoming a Groq request body, and a Groq
response — success, refusal, rate limit or rejection — becoming either a ``ProviderCall`` the
audit trail can record or a ``GradingError`` classified correctly enough for the retry policy
above it to act on.

No test here makes a network call. ``httpx.AsyncClient`` is replaced with a stub, which is also
what lets a test assert on the request that *would* have been sent — including that the API key
never reaches a log line or an exception message.
"""

from typing import Any

import httpx
import pytest

from core.config.settings import settings
from core.services.ai import groq_provider as module
from core.services.ai.groq_provider import GroqProvider
from core.services.ai.types import GradingError, GradingFailureKind

SCHEMA: dict[str, Any] = {"type": "object", "properties": {"score": {"type": "integer"}}}
API_KEY = "gsk-test-key-not-a-real-one"


def _completion(**overrides: Any) -> dict[str, Any]:
    """
    Build a successful Groq chat completion body.

    Args:
        **overrides: Fields to replace on the default body.

    Returns:
        dict[str, Any]: A response body shaped like Groq's.
    """
    body: dict[str, Any] = {
        "id": "chatcmpl-abc123",
        "model": "openai/gpt-oss-120b",
        "choices": [{"message": {"content": '{"score": 72}'}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 512, "completion_tokens": 128, "total_tokens": 640},
    }
    body.update(overrides)
    return body


class StubClient:
    """Stands in for ``httpx.AsyncClient``, returning queued responses and recording requests."""

    def __init__(self, responses: list[httpx.Response | Exception], **_: Any) -> None:
        """
        Queue the responses this client will produce, in order.

        Args:
            responses: Responses to return, or exceptions to raise, one per call.
            **_: Client keyword arguments, which the adapter passes and this stub ignores.
        """
        self._responses = list(responses)
        self.requests: list[dict[str, Any]] = []

    async def __aenter__(self) -> "StubClient":
        """Enter the async context manager, returning this client."""
        return self

    async def __aexit__(self, *_: Any) -> None:
        """Exit the async context manager without suppressing anything."""

    async def post(self, url: str, *, json: dict[str, Any], headers: dict[str, str]) -> Any:
        """
        Record one request and return the next queued response.

        Args:
            url: Request URL.
            json: Request body.
            headers: Request headers.

        Returns:
            httpx.Response: The next queued response.

        Raises:
            Exception: When the queue holds an exception at this position.
        """
        self.requests.append({"url": url, "json": json, "headers": headers})
        nxt = self._responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


@pytest.fixture
def groq_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Configure Groq credentials for one test.

    `conftest` clears `GROQ_API_KEY` outright so the unconfigured behaviour stays testable, which
    means every test that needs a key opts in here rather than inheriting one from the machine.

    Args:
        monkeypatch: Pytest patching fixture.
    """
    monkeypatch.setattr(settings, "GROQ_API_KEY", API_KEY)
    monkeypatch.setattr(settings, "GRADING_MODEL", "openai/gpt-oss-120b")


@pytest.fixture(autouse=True)
def _forget_structured_output_support() -> None:
    """
    Clear the per-process record of which models lack structured outputs.

    The set is deliberately process-lifetime state, so without this a test that drives the
    fallback would silently change the request every later test asserts on.
    """
    module._NO_STRUCTURED_OUTPUT.clear()


def _install(monkeypatch: pytest.MonkeyPatch, *responses: httpx.Response | Exception) -> StubClient:
    """
    Replace the adapter's HTTP client with a stub returning the given responses.

    Args:
        monkeypatch: Pytest patching fixture.
        *responses: Responses to return, or exceptions to raise, in order.

    Returns:
        StubClient: The stub, for asserting on what was sent.
    """
    client = StubClient(list(responses))
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: client)
    return client


def _response(status: int, *, json: dict[str, Any] | None = None, text: str = "") -> httpx.Response:
    """
    Build an httpx response.

    Args:
        status: HTTP status code.
        json: JSON body, when the response has one.
        text: Raw body, for non-JSON responses.

    Returns:
        httpx.Response: The response.
    """
    if json is not None:
        return httpx.Response(status, json=json)
    return httpx.Response(status, text=text)


class TestConfiguration:
    """Construction refuses a deployment that cannot possibly grade."""

    def test_missing_api_key_fails_at_construction(self) -> None:
        """A misconfigured deployment is named as such, not discovered as a 401 from Groq."""
        with pytest.raises(GradingError) as caught:
            GroqProvider()

        assert caught.value.kind is GradingFailureKind.NOT_CONFIGURED

    def test_reports_its_own_name_and_the_configured_model(self, groq_configured: None) -> None:
        """The name is recorded on every grade event, so it is part of the contract."""
        provider = GroqProvider()

        assert provider.name == "groq"
        assert provider.model == "openai/gpt-oss-120b"


@pytest.mark.usefixtures("groq_configured")
class TestSuccessfulCall:
    """A successful response becomes a ProviderCall the audit trail can record."""

    async def test_posts_to_the_groq_completions_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The endpoint is derived from configuration rather than written into the call site."""
        client = _install(monkeypatch, _response(200, json=_completion()))

        await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert client.requests[0]["url"] == f"{settings.GROQ_BASE_URL}/chat/completions"

    async def test_grades_deterministically_and_caps_output(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A resubmitted identical answer must not score differently, so temperature is zero."""
        client = _install(monkeypatch, _response(200, json=_completion()))

        await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        body = client.requests[0]["json"]
        assert body["temperature"] == 0.0
        assert body["max_tokens"] == module.MAX_OUTPUT_TOKENS
        assert body["model"] == "openai/gpt-oss-120b"

    async def test_constrains_the_response_with_the_schema(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Structural prevention first; validation against the rubric still runs afterwards."""
        client = _install(monkeypatch, _response(200, json=_completion()))

        await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert client.requests[0]["json"]["response_format"] == {
            "type": "json_schema",
            "json_schema": {"name": "grade", "strict": True, "schema": SCHEMA},
        }

    async def test_returns_content_usage_and_identity(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Everything a grade event needs to attribute a grade later."""
        _install(monkeypatch, _response(200, json=_completion()))

        call = await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert call.content == '{"score": 72}'
        assert call.provider == "groq"
        assert call.model == "openai/gpt-oss-120b"
        assert call.model_version == "openai/gpt-oss-120b"
        assert call.request_id == "chatcmpl-abc123"
        assert call.input_tokens == 512
        assert call.output_tokens == 128
        assert call.latency_ms >= 0

    async def test_records_no_cost_because_groq_reports_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A null cost is a stated fact about the provider, not a number guessed from a rate card."""
        _install(monkeypatch, _response(200, json=_completion()))

        call = await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert call.cost is None

    async def test_drops_unusable_usage_rather_than_failing_the_grade(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Usage is reporting, not correctness. A grade that worked must not fail over it."""
        body = _completion(usage={"prompt_tokens": "many", "completion_tokens": -3})
        _install(monkeypatch, _response(200, json=body))

        call = await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert call.input_tokens is None
        assert call.output_tokens is None
        assert call.content == '{"score": 72}'


@pytest.mark.usefixtures("groq_configured")
class TestStructuredOutputFallback:
    """Only part of Groq's catalogue accepts json_schema; the rest must still grade."""

    async def test_retries_without_the_schema_when_the_model_rejects_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The schema is an aid to well-formed output, never what makes a grade trustworthy."""
        rejection = _response(
            400, json={"error": {"message": "response_format json_schema is not supported"}}
        )
        client = _install(monkeypatch, rejection, _response(200, json=_completion()))

        call = await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert len(client.requests) == 2
        assert "response_format" in client.requests[0]["json"]
        assert "response_format" not in client.requests[1]["json"]
        assert call.content == '{"score": 72}'

    async def test_remembers_the_model_lacks_support_for_the_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The discovery costs a wasted call, so it is paid once rather than on every grade."""
        rejection = _response(400, json={"error": {"message": "json_validate_failed"}})
        _install(monkeypatch, rejection, _response(200, json=_completion()))
        provider = GroqProvider()
        await provider.complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        client = _install(monkeypatch, _response(200, json=_completion()))
        await provider.complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert len(client.requests) == 1
        assert "response_format" not in client.requests[0]["json"]

    async def test_a_400_about_something_else_is_not_retried(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unknown model fails identically on every retry; retrying only delays the student."""
        rejection = _response(400, json={"error": {"message": "model `nope` does not exist"}})
        client = _install(monkeypatch, rejection)

        with pytest.raises(GradingError) as caught:
            await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert len(client.requests) == 1
        assert caught.value.kind is GradingFailureKind.NOT_CONFIGURED


@pytest.mark.usefixtures("groq_configured")
class TestFailures:
    """Every failure is classified so the retry policy above can act on it."""

    @pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
    async def test_transient_statuses_are_retryable(
        self, monkeypatch: pytest.MonkeyPatch, status: int
    ) -> None:
        """Rate limiting and provider outages resolve on their own; the sweep should try again."""
        _install(monkeypatch, _response(status, text="upstream unavailable"))

        with pytest.raises(GradingError) as caught:
            await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert caught.value.kind is GradingFailureKind.PROVIDER_ERROR
        assert caught.value.kind.is_retryable

    @pytest.mark.parametrize("status", [401, 403, 404, 422])
    async def test_client_errors_are_not_retryable(
        self, monkeypatch: pytest.MonkeyPatch, status: int
    ) -> None:
        """A bad key or an unknown model will fail the same way five more times."""
        _install(monkeypatch, _response(status, text="nope"))

        with pytest.raises(GradingError) as caught:
            await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert caught.value.kind is GradingFailureKind.NOT_CONFIGURED

    async def test_a_timeout_is_reported_as_a_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Distinct from a provider error, because a timeout may have been charged for."""
        _install(monkeypatch, httpx.ReadTimeout("timed out"))

        with pytest.raises(GradingError) as caught:
            await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert caught.value.kind is GradingFailureKind.TIMEOUT

    async def test_a_transport_failure_is_a_provider_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DNS, TLS and connection failures are all worth another attempt."""
        _install(monkeypatch, httpx.ConnectError("no route"))

        with pytest.raises(GradingError) as caught:
            await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert caught.value.kind is GradingFailureKind.PROVIDER_ERROR

    async def test_a_non_json_body_fails_rather_than_being_graded(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An HTML error page from an intermediary is not a grade."""
        _install(monkeypatch, _response(200, text="<html>502 Bad Gateway</html>"))

        with pytest.raises(GradingError) as caught:
            await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert caught.value.kind is GradingFailureKind.PROVIDER_ERROR

    @pytest.mark.parametrize(
        "body",
        [
            {"choices": []},
            {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
            {"choices": [{"message": {}, "finish_reason": "content_filter"}]},
        ],
        ids=["no choices", "truncated", "filtered"],
    )
    async def test_empty_content_is_a_failure_not_an_empty_grade(
        self, monkeypatch: pytest.MonkeyPatch, body: dict[str, Any]
    ) -> None:
        """An answer must never be scored on nothing. Retryable: the same prompt often succeeds."""
        _install(monkeypatch, _response(200, json=body))

        with pytest.raises(GradingError) as caught:
            await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert caught.value.kind is GradingFailureKind.PROVIDER_ERROR


@pytest.mark.usefixtures("groq_configured")
class TestSecrets:
    """The API key travels in one header and appears nowhere else."""

    async def test_authorises_with_a_bearer_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Groq authenticates the same way OpenRouter does; only the key differs."""
        client = _install(monkeypatch, _response(200, json=_completion()))

        await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert client.requests[0]["headers"]["Authorization"] == f"Bearer {API_KEY}"

    async def test_the_key_never_reaches_a_failure_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A GradingError is logged and stored on a grade event, so it must carry no secret."""
        _install(monkeypatch, _response(401, text=f"invalid key {API_KEY}"))

        with pytest.raises(GradingError) as caught:
            await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert API_KEY not in caught.value.message
        assert API_KEY not in str(caught.value)

    async def test_the_request_body_carries_no_credential(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The body is what a proxy or a captured payload would expose."""
        client = _install(monkeypatch, _response(200, json=_completion()))

        await GroqProvider().complete(system_prompt="s", user_prompt="u", json_schema=SCHEMA)

        assert API_KEY not in str(client.requests[0]["json"])
