"""Groq grading provider.

Every Groq-specific detail in the application lives here: the endpoint, the request shape, the
response shape, and how usage is read back. Nothing above this file knows the product talks to
Groq at all.

Groq exposes an OpenAI-compatible chat completions API, so the request body is shaped like
OpenRouter's. The two differences that matter are deliberate rather than incidental: Groq reports
no cost on a response, so the audit trail records the tokens and leaves cost null instead of
multiplying by a rate card this application would then have to keep in step; and only some of the
hosted models accept a ``json_schema`` response format, so the same structured-output fallback
OpenRouter needs is needed here too.

The API key is read from settings and used only in this server-side module. It is never included
in a response, a log line, or anything reachable from the browser.
"""

import time
from typing import Any

import httpx

from core import logger
from core.config.settings import settings
from core.services.ai.provider import GradingProvider
from core.services.ai.types import GradingError, GradingFailureKind, ProviderCall

logging = logger(__name__)

COMPLETIONS_PATH = "/chat/completions"
# Grading is a short, bounded extraction task, so output is capped to stop a runaway generation
# turning one answer into an unbounded bill. Matches the OpenRouter adapter: the cap has to fit
# the longest *legitimate* response, and a truncated grade is a wasted call rather than a saved
# one.
MAX_OUTPUT_TOKENS = 1600
# Deterministic grading. The same answer against the same rubric should not score differently on
# two submissions; a student who resubmits identical work and sees a different number has no
# reason to trust any of the numbers.
TEMPERATURE = 0.0
# Status codes worth another attempt: rate limiting, and the provider's own transient failures.
# Groq answers 429 both for a per-minute rate limit and for a spent daily token allowance; only
# the first resolves on its own, and the retry sweep's lifetime cap is what bounds the second.
RETRYABLE_STATUSES = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

# Groq supports json_schema on a subset of its catalogue and rejects the whole request with a 400
# elsewhere. Models found to lack it are remembered for the life of the process so the discovery
# is paid once rather than on every grade.
_NO_STRUCTURED_OUTPUT: set[str] = set()
# Substrings that identify a rejection caused specifically by the schema constraint, as opposed
# to a bad key or an unknown model. Matched case-insensitively against the error body.
_STRUCTURED_OUTPUT_REJECTIONS = (
    "structured output",
    "response_format",
    "json_schema",
    "json_validate_failed",
)


class GroqProvider(GradingProvider):
    """Grading provider backed by Groq's OpenAI-compatible chat completions API."""

    name = "groq"

    def __init__(self) -> None:
        """
        Initialise the provider against the configured Groq deployment.

        Raises:
            GradingError: If no API key is configured. Failing here rather than at call time
                means a misconfigured deployment is discovered when grading is first attempted,
                with a message naming the cause, instead of as a 401 from a third party.
        """
        if not settings.GROQ_API_KEY:
            logging.error("Groq grading is selected but GROQ_API_KEY is not set")
            raise GradingError(
                GradingFailureKind.NOT_CONFIGURED,
                "Groq grading is selected but no API key is configured",
            )
        self._base_url = str(settings.GROQ_BASE_URL).rstrip("/")
        self._api_key = settings.GROQ_API_KEY

    async def complete(
        self, *, system_prompt: str, user_prompt: str, json_schema: dict[str, Any]
    ) -> ProviderCall:
        """
        Send one grading prompt to Groq and return the response.

        Constrains the response with a strict JSON schema so the model is structurally prevented
        from returning prose, rather than merely asked not to. Validation still runs afterwards:
        most of Groq's catalogue does not honour the constraint, and the models that do can still
        return values that are well-formed but wrong.

        Args:
            system_prompt: The grading instructions.
            user_prompt: The rubric and the fenced student answer.
            json_schema: Schema the response content must conform to.

        Returns:
            ProviderCall: Content plus usage, latency and request identity.

        Raises:
            GradingError: On timeout, transport failure, an error status, or a response carrying
                no usable content.
        """
        started = time.perf_counter()
        structured = self.model not in _NO_STRUCTURED_OUTPUT
        response = await self._post(
            self._payload(system_prompt, user_prompt, json_schema, structured), started
        )

        # A model that cannot honour the schema constraint rejects the whole request. Dropping
        # the constraint and asking again is safe: the schema is an aid to getting well-formed
        # output, never the thing that makes it trustworthy. Validation against the rubric is
        # what does that, and it runs identically either way.
        if structured and response.status_code == 400 and self._rejected_the_schema(response):
            logging.warning(
                f"Model {self.model} does not support structured outputs; "
                f"falling back to prompt-constrained JSON for the rest of this process"
            )
            _NO_STRUCTURED_OUTPUT.add(self.model)
            response = await self._post(
                self._payload(system_prompt, user_prompt, json_schema, False), started
            )

        latency_ms = self._elapsed(started)
        if response.status_code >= 400:
            self._raise_for_status(response, latency_ms)

        return self._parse(response, latency_ms=latency_ms)

    def _payload(
        self,
        system_prompt: str,
        user_prompt: str,
        json_schema: dict[str, Any],
        structured: bool,
    ) -> dict[str, Any]:
        """
        Build the chat completion request body.

        Args:
            system_prompt: The grading instructions.
            user_prompt: The rubric and the fenced student answer.
            json_schema: Schema the response content should conform to.
            structured: Whether to constrain the response with the schema.

        Returns:
            dict[str, Any]: The request body.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if structured:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "grade", "strict": True, "schema": json_schema},
            }
        return payload

    async def _post(self, payload: dict[str, Any], started: float) -> httpx.Response:
        """
        Send one request to the completions endpoint.

        Args:
            payload: The request body.
            started: Perf counter reading from when the overall call began, for timeout logging.

        Returns:
            httpx.Response: The response, including error statuses.

        Raises:
            GradingError: On timeout or transport failure.
        """
        try:
            async with httpx.AsyncClient(timeout=settings.GRADING_TIMEOUT_SECONDS) as client:
                return await client.post(
                    f"{self._base_url}{COMPLETIONS_PATH}",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                )
        except httpx.TimeoutException as error:
            logging.error(f"Groq grading call timed out after {self._elapsed(started)}ms")
            raise GradingError(GradingFailureKind.TIMEOUT, "Grading provider timed out") from error
        except httpx.HTTPError as error:
            # Deliberately does not interpolate the exception into the message: httpx puts the
            # request URL in it, and the URL is not sensitive but the habit is worth keeping.
            logging.error(f"Groq grading call failed: {type(error).__name__}")
            raise GradingError(
                GradingFailureKind.PROVIDER_ERROR, "Could not reach the grading provider"
            ) from error

    @staticmethod
    def _rejected_the_schema(response: httpx.Response) -> bool:
        """
        Report whether a 400 was caused by the structured-output constraint.

        Matched on the error text rather than assumed from the status, so a genuinely bad
        request — an unknown model, an invalid key — is not retried pointlessly. When a provider
        words its rejection differently the original error surfaces unchanged, which is correct;
        it simply does not self-heal.

        Args:
            response: The 400 response.

        Returns:
            bool: True when the body points at structured outputs.
        """
        body = response.text.lower()
        return any(marker in body for marker in _STRUCTURED_OUTPUT_REJECTIONS)

    def _raise_for_status(self, response: httpx.Response, latency_ms: int) -> None:
        """
        Convert an error status into a classified grading failure.

        A 4xx that is not rate limiting means the request itself is wrong — a bad key, an unknown
        model, a malformed schema — and will fail identically on every retry, so it is classified
        as non-retryable to avoid burning the retry budget and delaying the student.

        Args:
            response: The error response.
            latency_ms: How long the call took.

        Raises:
            GradingError: Always.
        """
        status = response.status_code
        retryable = status in RETRYABLE_STATUSES or status >= 500
        logging.error(
            f"Groq grading returned {status} after {latency_ms}ms (retryable={retryable})"
        )
        raise GradingError(
            GradingFailureKind.PROVIDER_ERROR if retryable else GradingFailureKind.NOT_CONFIGURED,
            f"Grading provider returned status {status}",
        )

    def _parse(self, response: httpx.Response, *, latency_ms: int) -> ProviderCall:
        """
        Extract content and accounting from a successful Groq response.

        Args:
            response: The successful response.
            latency_ms: How long the call took.

        Returns:
            ProviderCall: Content plus usage, latency and request identity.

        Raises:
            GradingError: If the body is not JSON or carries no message content.
        """
        try:
            body: dict[str, Any] = response.json()
        except ValueError as error:
            logging.error("Groq returned a non-JSON body")
            raise GradingError(
                GradingFailureKind.PROVIDER_ERROR, "Grading provider returned a non-JSON body"
            ) from error

        choices = body.get("choices") or []
        content = ""
        if choices and isinstance(choices[0], dict):
            content = (choices[0].get("message") or {}).get("content") or ""

        if not content.strip():
            # A refusal, a content filter, or a truncated generation all land here. Retryable,
            # because the same prompt frequently succeeds on a second call.
            finish_reason = choices[0].get("finish_reason") if choices else None
            logging.error(f"Groq returned empty content (finish_reason={finish_reason})")
            raise GradingError(
                GradingFailureKind.PROVIDER_ERROR, "Grading provider returned no content"
            )

        usage = body.get("usage") or {}
        return ProviderCall(
            content=content,
            provider=self.name,
            model=self.model,
            # Groq echoes the model that served the request. It normally matches what was asked
            # for, but a grade is only attributable if it records what really ran.
            model_version=body.get("model"),
            request_id=body.get("id"),
            input_tokens=_as_int(usage.get("prompt_tokens")),
            output_tokens=_as_int(usage.get("completion_tokens")),
            # Groq reports no cost, only tokens. The column is left null rather than filled by
            # multiplying tokens against a rate card copied into this repository, which would be
            # a number that silently goes wrong the next time Groq changes its pricing.
            cost=None,
            latency_ms=latency_ms,
            raw_response=body,
        )

    @staticmethod
    def _elapsed(started: float) -> int:
        """
        Return milliseconds elapsed since a perf counter reading.

        Args:
            started: Value from ``time.perf_counter`` when the call began.

        Returns:
            int: Elapsed milliseconds.
        """
        return int((time.perf_counter() - started) * 1000)


def _as_int(value: Any) -> int | None:
    """
    Coerce a usage field to a non-negative integer, or None.

    Usage accounting is reporting, not correctness, so an unexpected type is dropped rather than
    failing a grade that otherwise succeeded.

    Args:
        value: Raw value from the provider payload.

    Returns:
        int | None: The integer value, or None when absent or unusable.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value) if value >= 0 else None
