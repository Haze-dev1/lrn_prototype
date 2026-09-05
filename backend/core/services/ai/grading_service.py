"""Grading orchestration.

Owns the sequence that turns a persisted answer into a grade: build the prompt, call the
provider, validate what came back against the rubric that produced it, write the result, and
append an audit record — for failures as well as successes.

The invariant this module exists to protect is that **an answer is never lost to an AI failure**.
The attempt is already in the database before anything here runs; every failure path leaves the
answer intact and the attempt in a state the interface can explain and the retry sweep can pick
up. Nothing here writes a score of zero. A zero is a judgement about a student's answer, and a
provider timeout is not a judgement about anything.
"""

import asyncio
import json
import uuid
from typing import Any

from core import logger
from core.config.settings import settings
from core.constants.enums import Band, GradingStatus, ValidationStatus
from core.cruds.attempt_crud import CRUDAttempt, CRUDGradeEvent
from core.cruds.category_crud import CRUDCategory
from core.cruds.question_crud import CRUDQuestion, CRUDQuestionVersion
from core.models.attempt_model import Attempt
from core.services.ai.prompts import (
    GRADE_JSON_SCHEMA,
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    build_fence,
    build_user_prompt,
)
from core.services.ai.provider import GradingProvider, get_grading_provider
from core.services.ai.types import (
    GradeContext,
    GradeResult,
    GradingError,
    GradingFailureKind,
    ModelGradeOutput,
    ProviderCall,
)
from core.services.analytics.events import AnalyticsEvent
from core.services.analytics.service import track

logging = logger(__name__)

# First backoff before an immediate retry; doubles per attempt. Short, because a student is
# waiting on the result and the scheduled sweep is what covers the longer failures.
RETRY_BACKOFF_SECONDS = 1.0

_FAILURE_TO_VALIDATION: dict[GradingFailureKind, ValidationStatus] = {
    GradingFailureKind.TIMEOUT: ValidationStatus.TIMEOUT,
    GradingFailureKind.PROVIDER_ERROR: ValidationStatus.PROVIDER_ERROR,
    GradingFailureKind.NOT_CONFIGURED: ValidationStatus.PROVIDER_ERROR,
    GradingFailureKind.INVALID_SCHEMA: ValidationStatus.INVALID_SCHEMA,
    GradingFailureKind.INVALID_VALUES: ValidationStatus.INVALID_VALUES,
}


class GradingService:
    """Grades persisted attempts and records the audit trail for every call."""

    def __init__(self, *, provider: GradingProvider | None = None) -> None:
        """
        Initialise the service, optionally against a specific provider.

        The provider is injectable so tests can drive failure paths — a timeout, malformed JSON,
        an invented concept key — without patching module internals or making a network call.
        Left unset, the configured provider is built lazily on first use, so importing this module
        never requires a provider to be configured.

        Args:
            provider: Provider to grade through. Defaults to the configured one.
        """
        self._provider = provider
        self.CRUDAttempt = CRUDAttempt()
        self.CRUDGradeEvent = CRUDGradeEvent()
        self.CRUDQuestion = CRUDQuestion()
        self.CRUDQuestionVersion = CRUDQuestionVersion()
        self.CRUDCategory = CRUDCategory()

    async def grade_attempt(self, *, attempt_id: uuid.UUID) -> Attempt | None:
        """
        Grade one persisted attempt and record the outcome.

        Reads the question version by the ID stored on the attempt, never the currently published
        one, so a rubric edit between submission and grading cannot grade an answer against a
        rubric the student never saw.

        Every exit path leaves the attempt in a coherent state: GRADED with a full result, or
        PENDING for another sweep, or FAILED once retries are exhausted. It never raises to its
        caller, because the caller is a background task or a scheduled sweep and an exception
        there would lose the outcome rather than record it.

        Args:
            attempt_id: The attempt to grade.

        Returns:
            Attempt | None: The attempt in its resulting state, or None if it no longer exists.
        """
        logging.info("Executing GradingService.grade_attempt")
        attempt = await self.CRUDAttempt.get_by_id(attempt_id=attempt_id)
        if attempt is None:
            logging.warning(f"No attempt found to grade with id: {attempt_id}")
            return None
        if attempt.grading_status == GradingStatus.GRADED:
            # Already graded: a retry sweep racing the inline background task, or a duplicate
            # submit. Re-grading would rewrite a grade the student has already seen.
            logging.info(f"Attempt {attempt_id} is already graded; skipping")
            return attempt

        try:
            context = await self._build_context(attempt)
        except GradingError as error:
            # The attempt references content that cannot produce a grade. Retrying cannot help,
            # so it fails immediately and stops consuming the sweep's budget.
            logging.error(f"Cannot grade attempt {attempt_id}: {error.message}")
            await self._record_failure(attempt=attempt, error=error, call=None, terminal=True)
            return await self.CRUDAttempt.get_by_id(attempt_id=attempt_id)

        await self.CRUDAttempt.set_grading_status(
            attempt_id=attempt_id, status=GradingStatus.GRADING
        )

        # Held outside the try so a validation failure still records what the provider
        # charged and how long it took. A malformed response is the case most worth
        # investigating, and discarding its accounting would hide exactly that.
        call: ProviderCall | None = None
        try:
            call = await self._call_provider(context)
            result = self._validate(call.content, context)
        except GradingError as error:
            await self._record_failure(
                attempt=attempt,
                error=error,
                call=call,
                terminal=not error.kind.is_retryable,
            )
            return await self.CRUDAttempt.get_by_id(attempt_id=attempt_id)

        await self.CRUDGradeEvent.create(
            obj_in={
                **self._audit_fields(attempt=attempt, call=call, context=context),
                "validation_status": ValidationStatus.VALID,
                "error_message": self._quality_note(result),
            }
        )
        graded = await self.CRUDAttempt.set_grade_result(
            attempt_id=attempt_id, result=result.as_attempt_fields()
        )
        logging.info(f"Graded attempt {attempt_id}: score={result.score} band={result.band}")
        # Counts and identifiers only. The feedback text, the concepts and the student's answer
        # all stay here — this event exists to measure grading latency, cost and score
        # distribution, none of which needs the words.
        track(
            event=AnalyticsEvent.GRADE_RECEIVED,
            user_id=attempt.user_id,
            properties={
                "attempt_id": attempt_id,
                "session_id": attempt.session_id,
                "score": result.score,
                "band": result.band,
                "concepts_hit_count": len(result.concepts_hit),
                "concepts_missed_count": len(result.concepts_missed),
                "provider": call.provider,
                "model": call.model,
                "latency_ms": call.latency_ms,
                "retry_count": attempt.retry_count,
            },
        )
        return graded

    async def retry_unresolved(self, *, limit: int = 50) -> dict[str, int]:
        """
        Grade attempts whose grading never resolved.

        This is the safety net behind the whole design. Inline grading runs in a background task,
        so a container restart, a deploy, or a crash between persisting an answer and writing its
        grade would otherwise strand the attempt forever. The sweep picks up anything left in a
        non-graded state past the age threshold and finishes it.

        The age threshold matters: without it the sweep would pick up an attempt still being
        graded by the request that created it, and two concurrent calls would grade one answer
        twice at double the cost.

        Args:
            limit: Maximum attempts to process in one sweep.

        Returns:
            dict[str, int]: Counts of attempts examined, graded, failed, and abandoned.
        """
        logging.info("Executing GradingService.retry_unresolved")
        due = await self.CRUDAttempt.list_due_for_retry(
            older_than_seconds=settings.GRADING_RETRY_AFTER_SECONDS, limit=limit
        )
        summary = {"examined": len(due), "graded": 0, "failed": 0, "abandoned": 0}

        for attempt in due:
            if attempt.retry_count >= settings.GRADING_MAX_LIFETIME_RETRIES:
                # Stop paying for an answer that has failed repeatedly. It stays FAILED and
                # visible rather than being scored or deleted, so it can be investigated and the
                # student can be told plainly that grading did not succeed.
                if attempt.grading_status != GradingStatus.FAILED:
                    await self.CRUDAttempt.set_grading_status(
                        attempt_id=attempt.id, status=GradingStatus.FAILED
                    )
                summary["abandoned"] += 1
                logging.warning(
                    f"Abandoning grading for attempt {attempt.id} after "
                    f"{attempt.retry_count} retries"
                )
                continue

            await self.CRUDAttempt.set_grading_status(
                attempt_id=attempt.id, status=GradingStatus.PENDING, increment_retry=True
            )
            regraded = await self.grade_attempt(attempt_id=attempt.id)
            if regraded is not None and regraded.grading_status == GradingStatus.GRADED:
                summary["graded"] += 1
            else:
                summary["failed"] += 1

        if summary["examined"]:
            logging.info(f"Grading retry sweep: {summary}")
        return summary

    # ----------------------------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------------------------

    async def _build_context(self, attempt: Attempt) -> GradeContext:
        """
        Assemble the rubric and answer for one attempt.

        Args:
            attempt: The persisted attempt.

        Returns:
            GradeContext: Everything the prompt needs.

        Raises:
            GradingError: If the question or the version the attempt was pinned to is missing.
        """
        version = await self.CRUDQuestionVersion.get_by_id(version_id=attempt.question_version_id)
        question = await self.CRUDQuestion.get_by_id(question_id=attempt.question_id)
        if version is None or question is None:
            raise GradingError(
                GradingFailureKind.NOT_CONFIGURED,
                "The attempt references a question or version that no longer exists",
            )

        category = await self.CRUDCategory.get_by_slug(slug=question.category_slug)
        return GradeContext(
            question_prompt=version.prompt,
            ideal_answer=version.ideal_answer,
            expected_concepts=list(version.expected_concepts or []),
            common_mistakes=list(version.common_mistakes or []),
            rubric=dict(version.rubric or {}),
            student_answer=attempt.answer,
            category_name=category.name if category else question.category_slug,
            version_number=version.version,
        )

    async def _call_provider(self, context: GradeContext) -> ProviderCall:
        """
        Send one grading prompt through the configured provider, retrying transient failures.

        This immediate retry exists alongside the scheduled sweep because they solve different
        problems. The sweep is the durability guarantee: it survives a crash and cannot lose an
        answer, but it only runs every few minutes. A single 429 or 503 is far more common than a
        crash, and making a student wait minutes for a blip that clears in a second is a bad
        trade. So transient failures are retried here with a short backoff, and everything the
        retries do not fix falls through to the sweep.

        A fresh fence is generated per call, so a retry cannot reuse a delimiter that appeared in
        a response the provider may have logged.

        Args:
            context: The rubric and student answer.

        Returns:
            ProviderCall: The provider's raw response and accounting.

        Raises:
            GradingError: If the provider could not be built, or every attempt failed.
        """
        if self._provider is None:
            self._provider = get_grading_provider()

        attempts = max(1, settings.GRADING_MAX_RETRIES + 1)
        last_error: GradingError | None = None

        for attempt_number in range(attempts):
            try:
                return await self._provider.complete(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=build_user_prompt(context, fence=build_fence()),
                    json_schema=GRADE_JSON_SCHEMA,
                )
            except GradingError as error:
                last_error = error
                if not error.kind.is_retryable or attempt_number == attempts - 1:
                    raise
                delay = RETRY_BACKOFF_SECONDS * (2**attempt_number)
                logging.warning(
                    f"Grading call failed ({error.kind}); retrying in {delay}s "
                    f"({attempt_number + 1}/{attempts - 1})"
                )
                await asyncio.sleep(delay)

        # Unreachable: the loop either returns or raises. Present so the type checker sees a
        # terminating path rather than an implicit None.
        raise last_error or GradingError(
            GradingFailureKind.PROVIDER_ERROR, "Grading provider produced no result"
        )

    def _validate(self, content: str, context: GradeContext) -> GradeResult:
        """
        Turn a model's claimed grade into one the server will record.

        Three things are checked, in order of how badly each would corrupt the evidence:

        - **Shape.** Parsed against ``ModelGradeOutput``; anything malformed is rejected outright.
        - **Keys.** Concept and mistake keys are reconciled against the rubric and unknown ones
          are dropped. This matters more than it looks: concept keys are aggregated into mastery
          and grouped in review, so a model that invents ``net_debt_bridge`` where the rubric says
          ``net_debt`` would silently fork a student's history into two unrelated concepts.
        - **Band.** Derived from the score using the question's own thresholds, overriding
          whatever the model returned. A score and a band that contradict each other cannot be
          resolved after the fact and would render as an incoherent grade panel; disagreement is
          recorded as a quality signal instead.

        Args:
            content: Raw content returned by the provider.
            context: The rubric the grade must be consistent with.

        Returns:
            GradeResult: A grade safe to persist.

        Raises:
            GradingError: If the content is not parseable or does not satisfy the schema.
        """
        try:
            parsed = json.loads(extract_json_object(content))
        except (ValueError, TypeError) as error:
            logging.error("Grading provider returned content that is not valid JSON")
            raise GradingError(
                GradingFailureKind.INVALID_SCHEMA, "Provider response was not valid JSON"
            ) from error

        if not isinstance(parsed, dict):
            raise GradingError(
                GradingFailureKind.INVALID_SCHEMA, "Provider response was not a JSON object"
            )

        try:
            output = ModelGradeOutput.model_validate(parsed)
        except Exception as error:
            logging.error("Grading provider returned JSON that does not match the grade schema")
            raise GradingError(
                GradingFailureKind.INVALID_VALUES,
                "Provider response did not match the grade schema",
            ) from error

        known_concepts = set(context.concept_keys)
        known_mistakes = set(context.mistake_keys)
        hit, dropped_hit = _reconcile(output.concepts_hit, known_concepts)
        missed, dropped_missed = _reconcile(output.concepts_missed, known_concepts)
        mistakes, dropped_mistakes = _reconcile(output.mistake_flags, known_mistakes)

        # A concept cannot be both demonstrated and absent. When a model says both, the
        # conservative reading is that it was not demonstrated.
        hit = [key for key in hit if key not in set(missed)]

        band = derive_band(output.score, context.band_thresholds())
        dropped = dropped_hit + dropped_missed + dropped_mistakes
        if dropped:
            logging.warning(
                f"Grading model returned {len(dropped)} key(s) not declared by the rubric"
            )

        return GradeResult(
            score=output.score,
            band=band,
            feedback=output.feedback.strip(),
            concepts_hit=hit,
            concepts_missed=missed,
            mistake_flags=mistakes,
            band_disagreed=output.band.strip().lower().replace(" ", "_") != band.value,
            dropped_keys=dropped,
        )

    async def _record_failure(
        self,
        *,
        attempt: Attempt,
        error: GradingError,
        call: ProviderCall | None,
        terminal: bool,
    ) -> None:
        """
        Write the audit record for a failed grading call and set the attempt's state.

        The attempt returns to PENDING when another attempt is worthwhile, so the retry sweep
        picks it up, and moves to FAILED when it is not. Neither writes a score: the database
        rejects a non-graded attempt that carries one, which is the schema-level expression of
        "a grading failure never becomes a zero".

        Args:
            attempt: The attempt being graded.
            error: The classified failure.
            call: The provider call, when one completed far enough to have accounting.
            terminal: Whether to give up rather than leave it for the sweep.
        """
        await self.CRUDGradeEvent.create(
            obj_in={
                "attempt_id": attempt.id,
                "provider": call.provider if call else self._provider_name(),
                "provider_request_id": call.request_id if call else None,
                "model": call.model if call else settings.GRADING_MODEL,
                "model_version": call.model_version if call else None,
                "prompt_version": PROMPT_VERSION,
                "rubric_version": 0,
                "input_tokens": call.input_tokens if call else None,
                "output_tokens": call.output_tokens if call else None,
                "latency_ms": call.latency_ms if call else None,
                "estimated_cost": call.cost if call else None,
                "raw_response": call.raw_response if call else None,
                "validation_status": _FAILURE_TO_VALIDATION.get(
                    error.kind, ValidationStatus.PROVIDER_ERROR
                ).value,
                "error_message": error.message,
                "retry_count": attempt.retry_count,
            }
        )
        await self.CRUDAttempt.set_grading_status(
            attempt_id=attempt.id,
            status=GradingStatus.FAILED if terminal else GradingStatus.PENDING,
        )
        logging.warning(
            f"Grading failed for attempt {attempt.id} ({error.kind}); "
            f"{'giving up' if terminal else 'left for retry'}"
        )

    def _audit_fields(
        self, *, attempt: Attempt, call: ProviderCall, context: GradeContext
    ) -> dict[str, Any]:
        """
        Build the audit record for a completed grading call.

        Args:
            attempt: The attempt being graded.
            call: The provider call and its accounting.
            context: The rubric used, for its version.

        Returns:
            dict[str, Any]: Grade event fields, excluding validation status.
        """
        return {
            "attempt_id": attempt.id,
            "provider": call.provider,
            "provider_request_id": call.request_id,
            "model": call.model,
            "model_version": call.model_version,
            "prompt_version": PROMPT_VERSION,
            "rubric_version": context.version_number,
            "input_tokens": call.input_tokens,
            "output_tokens": call.output_tokens,
            "latency_ms": call.latency_ms,
            "estimated_cost": call.cost,
            "raw_response": call.raw_response,
            "retry_count": attempt.retry_count,
        }

    def _provider_name(self) -> str:
        """
        Return the provider's name without forcing one to be constructed.

        A failure that happened *because* no provider could be built must still be auditable, so
        this falls back to configuration rather than raising again.

        Returns:
            str: Provider name.
        """
        return self._provider.name if self._provider else settings.GRADING_PROVIDER

    @staticmethod
    def _quality_note(result: GradeResult) -> str | None:
        """
        Summarise non-fatal quality signals for the audit trail.

        Recorded on a *successful* grade so a model that is drifting — inventing keys, or
        disagreeing with the band its own score implies — is visible before it becomes a
        correctness problem.

        Args:
            result: The validated grade.

        Returns:
            str | None: A short note, or None when the response was clean.
        """
        notes = []
        if result.band_disagreed:
            notes.append("model band disagreed with the score")
        if result.dropped_keys:
            notes.append(f"dropped {len(result.dropped_keys)} undeclared key(s)")
        return "; ".join(notes) or None


def extract_json_object(content: str) -> str:
    """
    Recover the JSON object from a model response that may be wrapped in other text.

    Models are asked for bare JSON and frequently return something else anyway: a markdown code
    fence, a sentence of preamble, or a closing remark after the object. Discarding those
    responses would throw away grades that are perfectly good apart from their packaging, and
    would make grading quality depend on how obedient a particular model happens to be about
    formatting.

    This deliberately does not repair malformed JSON. It locates the object and hands it to the
    parser unchanged; if what is inside is broken, that is a real failure and must surface as one.

    Args:
        content: Raw content returned by the provider.

    Returns:
        str: The substring most likely to be the JSON object, or the input when none is found.
    """
    text = content.strip()

    if text.startswith("```"):
        # Drop the opening fence and its optional language tag, then the closing fence.
        text = text.split("\n", 1)[-1] if "\n" in text else text[3:]
        closing = text.rfind("```")
        if closing != -1:
            text = text[:closing]
        text = text.strip()

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text


def derive_band(score: int, thresholds: dict[str, int]) -> Band:
    """
    Map a score to its band using a question's own thresholds.

    Kept a module-level function because the same mapping is needed wherever a score is displayed
    without re-grading, and because it is the single definition of what "Strong" means.

    Args:
        score: Validated score, 0-100.
        thresholds: Band floors, from the rubric or the product default.

    Returns:
        Band: The band the score falls into.
    """
    if score >= thresholds["strong"]:
        return Band.STRONG
    if score >= thresholds["developing"]:
        return Band.DEVELOPING
    return Band.NEEDS_WORK


def _reconcile(returned: list[str], declared: set[str]) -> tuple[list[str], list[str]]:
    """
    Split returned keys into those the rubric declared and those it did not.

    Comparison is case- and separator-insensitive, because a model returning ``Net Debt`` for
    ``net_debt`` has identified the right concept and dropping it would understate the student.
    A key that matches nothing is dropped, never coerced to the nearest one: a wrong concept
    recorded against a student is worse than a missing one.

    Args:
        returned: Keys the model reported.
        declared: Keys the rubric declares.

    Returns:
        tuple[list[str], list[str]]: Recognised keys in declared form, and dropped keys.
    """
    lookup = {_normalise(key): key for key in declared}
    recognised: list[str] = []
    dropped: list[str] = []

    for key in returned:
        canonical = lookup.get(_normalise(key))
        if canonical is None:
            dropped.append(key)
        elif canonical not in recognised:
            recognised.append(canonical)
    return recognised, dropped


def _normalise(key: str) -> str:
    """
    Reduce a concept key to a comparable form.

    Args:
        key: Raw key.

    Returns:
        str: Lowercase key with separators collapsed.
    """
    return key.strip().lower().replace(" ", "_").replace("-", "_")
