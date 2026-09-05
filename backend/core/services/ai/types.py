"""Domain types for AI grading.

This module is the boundary the rest of the application sees. Nothing outside
``core.services.ai`` should know that OpenRouter exists, what a chat completion is, or how a
model was prompted — it consumes ``GradeResult`` and ``GradingOutcome`` and nothing else.

The split between ``ModelGradeOutput`` and ``GradeResult`` is deliberate and is the validation
boundary. ``ModelGradeOutput`` is what a language model claimed, parsed but not trusted;
``GradeResult`` is what the server is willing to record against a student. Collapsing them would
mean a model that invents a concept key, or returns a score of 140, writes straight into the
evidence that mastery is computed from.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from core.constants.enums import Band

MIN_SCORE = 0
MAX_SCORE = 100
MAX_FEEDBACK_LENGTH = 2000
# A model that returns more keys than the rubric declares is malfunctioning, not being thorough.
# The cap bounds the work done reconciling them before the unknown ones are dropped anyway.
MAX_RETURNED_KEYS = 50

# Band floors used when a question's rubric does not specify its own. Chosen so "Strong" means a
# genuinely complete answer rather than a passing one: this is interview preparation, and a
# student told they are strong at 65 will be surprised in the room.
DEFAULT_BAND_THRESHOLDS: dict[str, int] = {"strong": 80, "developing": 55}


class GradingFailureKind(StrEnum):
    """Why a grading call did not produce a usable result.

    Distinguishes conditions worth retrying from conditions that will fail identically forever.
    Retrying a malformed rubric wastes money and delays the student's answer reaching a human's
    attention; not retrying a timeout throws away a grade that would have succeeded.
    """

    TIMEOUT = "timeout"
    PROVIDER_ERROR = "provider_error"
    INVALID_SCHEMA = "invalid_schema"
    INVALID_VALUES = "invalid_values"
    NOT_CONFIGURED = "not_configured"

    @property
    def is_retryable(self) -> bool:
        """
        Report whether another attempt could plausibly succeed.

        Returns:
            bool: True for transient transport and model-output failures.
        """
        return self in {
            GradingFailureKind.TIMEOUT,
            GradingFailureKind.PROVIDER_ERROR,
            GradingFailureKind.INVALID_SCHEMA,
            GradingFailureKind.INVALID_VALUES,
        }


class GradingError(Exception):
    """Raised when a grading call cannot produce a usable result."""

    def __init__(self, kind: GradingFailureKind, message: str) -> None:
        """
        Record why grading failed.

        Args:
            kind: The category of failure, which decides whether a retry is worthwhile.
            message: Operator-facing detail. Never contains rubric or student content.
        """
        super().__init__(message)
        self.kind = kind
        self.message = message


@dataclass(frozen=True)
class GradeContext:
    """Everything needed to grade one answer, assembled by the caller.

    Frozen because it is passed into prompt construction and provider calls that must not be able
    to mutate the rubric they were given.
    """

    question_prompt: str
    ideal_answer: str
    expected_concepts: list[dict[str, Any]]
    common_mistakes: list[dict[str, Any]]
    rubric: dict[str, Any]
    student_answer: str
    category_name: str
    #: The question version number this rubric came from, recorded on every grade event so a
    #: grade can be traced to the exact rubric that produced it.
    version_number: int

    @property
    def concept_keys(self) -> list[str]:
        """
        Return the declared expected-concept keys.

        Returns:
            list[str]: Keys the model is permitted to report as hit or missed.
        """
        return [str(entry["key"]) for entry in self.expected_concepts if entry.get("key")]

    @property
    def mistake_keys(self) -> list[str]:
        """
        Return the declared common-mistake keys.

        Returns:
            list[str]: Keys the model is permitted to report as mistakes.
        """
        return [str(entry["key"]) for entry in self.common_mistakes if entry.get("key")]

    def band_thresholds(self) -> dict[str, int]:
        """
        Return the score floors for each band, from the rubric or the product default.

        Read from the rubric so a question can be graded on its own curve — a judgement question
        and a definition question do not deserve the same bar — while a rubric that omits them
        still produces a consistent band.

        Returns:
            dict[str, int]: Floors keyed by band name.
        """
        thresholds = self.rubric.get("band_thresholds")
        if not isinstance(thresholds, dict):
            return dict(DEFAULT_BAND_THRESHOLDS)

        resolved = dict(DEFAULT_BAND_THRESHOLDS)
        for name in resolved:
            value = thresholds.get(name)
            if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 100:
                resolved[name] = value
        return resolved


class ModelGradeOutput(BaseModel):
    """The structured grade a model claimed to produce, parsed but not yet trusted.

    Field constraints here reject the shapes that are obviously wrong — a score of 300, a
    thousand concept keys. They deliberately do not check that the keys are *real*: that needs
    the rubric, and it happens in the grading service where the rubric is in hand.
    """

    score: int = Field(ge=MIN_SCORE, le=MAX_SCORE)
    band: str
    feedback: str = Field(min_length=1, max_length=MAX_FEEDBACK_LENGTH)
    concepts_hit: list[str] = Field(default_factory=list, max_length=MAX_RETURNED_KEYS)
    concepts_missed: list[str] = Field(default_factory=list, max_length=MAX_RETURNED_KEYS)
    mistake_flags: list[str] = Field(default_factory=list, max_length=MAX_RETURNED_KEYS)


@dataclass(frozen=True)
class GradeResult:
    """A validated grade the server is willing to record against a student.

    Every key here has been checked against the rubric that produced it, and the band is derived
    from the score rather than taken from the model, so a score and a band can never contradict
    each other in the interface.
    """

    score: int
    band: Band
    feedback: str
    concepts_hit: list[str]
    concepts_missed: list[str]
    mistake_flags: list[str]
    # Quality signals for the audit trail, not shown to students.
    band_disagreed: bool = False
    dropped_keys: list[str] = field(default_factory=list)

    def as_attempt_fields(self) -> dict[str, Any]:
        """
        Render the grade in the shape the attempt row stores.

        Returns:
            dict[str, Any]: Score, band, feedback, and the three key lists.
        """
        return {
            "score": self.score,
            "band": self.band.value,
            "feedback": self.feedback,
            "concepts_hit": self.concepts_hit,
            "concepts_missed": self.concepts_missed,
            "mistake_flags": self.mistake_flags,
        }


@dataclass(frozen=True)
class ProviderCall:
    """The raw outcome of one call to a grading provider.

    Carries the accounting a grade event needs regardless of whether the content validated, so a
    failed call is as auditable as a successful one — a grading regression cannot be attributed
    if the calls that went wrong left no trace.
    """

    content: str
    provider: str
    model: str
    latency_ms: int
    model_version: str | None = None
    request_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: Decimal | None = None
    raw_response: dict[str, Any] | None = None
