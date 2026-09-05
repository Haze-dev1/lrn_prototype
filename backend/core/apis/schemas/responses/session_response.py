"""Response schemas for sessions and diagnostic results.

The question shape here is the same protected one used everywhere else: prompt and metadata, and
nothing a student could use to reverse-engineer the grade. It is a separate class from anything
carrying an ideal answer, so a rubric cannot be added to a mid-session payload by accident.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.constants.enums import GradingStatus, SessionStatus, SessionType


class SessionQuestionResponse(BaseModel):
    """One question of a session, as presented to the student working through it."""

    position: int = Field(description="Zero-based position in the fixed server-decided order.")
    id: uuid.UUID
    question_version_id: uuid.UUID
    category_slug: str
    category_name: str
    subcategory: str | None = None
    difficulty: int = Field(ge=1, le=5)
    prompt: str
    attempt_id: uuid.UUID | None = Field(
        default=None, description="Set once this question has been answered."
    )
    grading_status: GradingStatus | None = None


class SelectionRationaleResponse(BaseModel):
    """Why a session was composed the way it was.

    Written at selection time and stored, not derived on read. A student's mastery moves as they
    practise, so an explanation recomputed later would describe a state that no longer produced
    this set — and the sentence would quietly stop being true.
    """

    strategy: str
    explanation: str = Field(description="Plain-language reason, shown to the student verbatim.")
    focus_category: str | None = None
    requested_category: str | None = None
    review_due_count: int = 0
    new_count: int = 0
    weak_category_count: int = 0


class SessionStateResponse(BaseModel):
    """A session and its ordered questions, for rendering or resuming an assessment."""

    id: uuid.UUID
    type: SessionType
    status: SessionStatus
    question_count: int
    answered_count: int
    started_at: datetime
    finished_at: datetime | None = None
    selection_rationale: SelectionRationaleResponse | None = None
    questions: list[SessionQuestionResponse] = Field(default_factory=list)
    resumed: bool = Field(
        default=False,
        description="True when this session already existed and was returned instead of a new one.",
    )


class GradingProgressResponse(BaseModel):
    """How much of a finished session has been graded.

    Reported separately from the results themselves because grading is asynchronous: a student who
    lands here immediately after their last answer must see progress rather than a score computed
    from partial evidence.
    """

    total: int
    answered: int
    graded: int
    failed: int
    pending: int
    grading_complete: bool


class CategoryResultResponse(BaseModel):
    """One category's outcome from a diagnostic."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    score: int = Field(ge=0, le=100, description="Stored mastery, so every surface agrees.")
    previous_score: int | None = None
    evidence_count: int
    session_scores: list[int] = Field(
        default_factory=list, description="This session's scores, as the evidence behind the score."
    )
    answered: int
    missed_concepts: list[str] = Field(default_factory=list)


class RecommendationResponse(BaseModel):
    """The single next action the results page pushes.

    One action rather than a list: the page exists to answer "what now", and five equally
    weighted options is how a student leaves without doing any of them.
    """

    action: str
    category_slug: str
    category_name: str
    reason: str = Field(description="Plain-language explanation, shown to the student verbatim.")


class SessionResultsResponse(BaseModel):
    """A finished session's results."""

    session_id: uuid.UUID
    status: SessionStatus
    finished_at: datetime | None = None
    progress: GradingProgressResponse
    categories: list[CategoryResultResponse] = Field(default_factory=list)
    strengths: list[str] = Field(
        default_factory=list, description="Category slugs, strongest first."
    )
    weaknesses: list[str] = Field(
        default_factory=list, description="Category slugs, weakest first."
    )
    recommendation: RecommendationResponse | None = None
