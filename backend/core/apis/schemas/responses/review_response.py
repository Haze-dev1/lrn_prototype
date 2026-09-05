"""Response schemas for review history and progress.

The review list carries a summary per attempt and deliberately not the student's answer or the
reference answer. A list is scanned rather than read, and shipping every answer in it would make
the page heavy in both senses. The full evidence lives on the attempt detail endpoint, which the
student opens one at a time.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from core.constants.enums import Band, GradeFlagReason, GradeFlagStatus


class ReviewItemResponse(BaseModel):
    """One graded attempt, summarised for a scannable list."""

    id: uuid.UUID
    question_id: uuid.UUID
    category_slug: str
    category_name: str
    difficulty: int = Field(ge=1, le=5)
    prompt: str
    score: int = Field(ge=0, le=100)
    band: Band
    concepts_missed: list[str] = Field(default_factory=list)
    submitted_at: datetime
    flagged: bool = Field(default=False, description="Whether the student disputed this grade.")


class ReviewListResponse(BaseModel):
    """A page of review history."""

    items: list[ReviewItemResponse]
    next_cursor: datetime | None = Field(
        default=None, description="Pass as `before` to fetch the next page; null when exhausted."
    )


class GradeFlagRequest(BaseModel):
    """A student's dispute of one of their own grades."""

    reason: GradeFlagReason
    comment: str | None = Field(default=None, max_length=1000)


class GradeFlagResponse(BaseModel):
    """The outcome of raising a flag."""

    id: uuid.UUID
    status: GradeFlagStatus
    already_flagged: bool = Field(
        default=False,
        description="True when the student had already flagged this grade; a flag is a statement, not a vote.",
    )


class CategoryProgressResponse(BaseModel):
    """A student's mastery in one category.

    ``score`` is null for a category with no graded evidence rather than zero. "Not measured" and
    "measured badly" are different claims, and rendering the first as the second would invent a
    readiness signal the product has no basis for.
    """

    slug: str
    name: str
    score: int | None = Field(default=None, ge=0, le=100)
    previous_score: int | None = Field(default=None, ge=0, le=100)
    evidence_count: int = 0
    last_attempt_at: datetime | None = None
    provisional: bool = Field(
        default=False, description="Score is real but backed by thin evidence."
    )


class TrendPointResponse(BaseModel):
    """Reconstructed mastery at one point in the past."""

    as_of: datetime
    scores: dict[str, int] = Field(default_factory=dict)
    overall: int | None = None


class ProgressResponse(BaseModel):
    """Everything the progress surface shows.

    Answers four questions and no others: where am I, am I improving, what am I weakest at, and
    what should I do next. Anything that does not answer one of those is deliberately absent.
    """

    categories: list[CategoryProgressResponse]
    trend: list[TrendPointResponse] = Field(default_factory=list)
    overall: int | None = None
    measured_categories: int = 0
    total_categories: int = 0
    total_evidence: int = 0
    movement: int | None = Field(
        default=None,
        description="Change in overall mastery across the window; null when history is too thin to say.",
    )
    weakest: str | None = None
    strongest: str | None = None
