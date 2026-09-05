"""Request schemas for answer submission."""

from pydantic import BaseModel, Field, field_validator

from core.models.attempt_model import MAX_ANSWER_LENGTH


class AttemptSubmitRequest(BaseModel):
    """A student's answer to one question of a session.

    The answer length is bounded here, at the database, and again before the text reaches the
    model. Three checks for one rule is not redundancy for its own sake: this one gives the
    student a clear validation error, the database one holds even if a future caller bypasses
    this schema, and the model-facing one is a cost control on a paid API call.
    """

    question_id: str = Field(description="Question being answered; must belong to the session.")
    answer: str = Field(min_length=1, max_length=MAX_ANSWER_LENGTH)
    time_taken_seconds: int | None = Field(
        default=None,
        ge=0,
        le=86400,
        description="Client-reported time on the question. Telemetry only; never affects a grade.",
    )

    @field_validator("answer")
    @classmethod
    def _require_content(cls, value: str) -> str:
        """
        Reject an answer that is only whitespace.

        ``min_length`` alone would accept a submission of spaces, which would be persisted as a
        real attempt and then graded — spending a model call to tell a student that nothing is
        nothing.

        Args:
            value: The submitted answer.

        Returns:
            str: The answer with surrounding whitespace removed.

        Raises:
            ValueError: If the answer has no content.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("An answer cannot be empty")
        return stripped


class PracticeStartRequest(BaseModel):
    """Payload starting a practice session.

    The size is validated against the offered sizes rather than accepted as any integer: the
    product offers three lengths, and a client asking for 500 questions is asking for 500 paid
    grading calls.
    """

    size: int = Field(description="Questions in the set. One of 5, 10 or 20.")
    category_slug: str | None = Field(
        default=None,
        max_length=100,
        description="Practise one category. Omit to let the engine choose across all of them.",
    )
