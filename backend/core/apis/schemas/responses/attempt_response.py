"""Response schemas for attempts and their grades.

Grade content is only ever rendered from an attempt the caller owns and that has finished
grading. The ungraded shape carries no score and no feedback fields at all — not nulls, but
absent — so an interface built against it cannot render a zero while grading is still in flight.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.constants.enums import Band, GradingStatus


class AttemptStateResponse(BaseModel):
    """An attempt's identity and grading state, without any grade content."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    question_id: uuid.UUID
    grading_status: GradingStatus
    submitted_at: datetime
    retry_count: int = Field(
        default=0, description="Grading calls made for this answer, for support and diagnostics."
    )


class GradedAttemptResponse(AttemptStateResponse):
    """A fully graded attempt, including the evidence behind the score.

    ``ideal_answer`` appears here and nowhere before submission: once a student has committed an
    answer it is teaching material, and until then it is the answer key. The scoring rubric is
    never included at any stage.
    """

    answer: str = Field(description="The student's own answer, for review.")
    score: int = Field(ge=0, le=100)
    band: Band
    feedback: str
    concepts_hit: list[str] = Field(default_factory=list)
    concepts_missed: list[str] = Field(default_factory=list)
    mistake_flags: list[str] = Field(default_factory=list)
    graded_at: datetime

    question_prompt: str
    ideal_answer: str
    category_slug: str
    category_name: str
    concept_labels: dict[str, str] = Field(
        default_factory=dict,
        description="Readable names for the concept and mistake keys above, for display.",
    )
    flagged: bool = Field(
        default=False, description="Whether the student has already disputed this grade."
    )


class AttemptSubmittedResponse(AttemptStateResponse):
    """The immediate answer to a submission.

    Returned as soon as the answer is durably stored, before grading has run. That ordering is
    the whole point: the student's work is safe the moment they submit, and a provider failure
    afterwards can delay a grade but can never lose an answer.
    """

    duplicate: bool = Field(
        default=False,
        description="True when this answer was already submitted and the original was returned.",
    )
