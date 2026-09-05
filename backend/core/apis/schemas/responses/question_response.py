"""Response schemas for questions.

This module is the enforcement point for question protection. There are two shapes and they are
deliberately separate types rather than one type with optional fields: a student-facing response
*cannot* carry a rubric, because the class it is built from has nowhere to put one. An accidental
`**version_data` splat produces a validation error, not a leak.
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.constants.enums import QuestionStatus, QuestionVersionStatus


class CategoryResponse(BaseModel):
    """A skill category, safe to expose publicly."""

    model_config = ConfigDict(from_attributes=True)

    slug: str
    name: str
    description: str | None = None
    display_order: int


# --------------------------------------------------------------------------------------
# Student-facing
# --------------------------------------------------------------------------------------


class QuestionForAnsweringResponse(BaseModel):
    """A question as presented to a student who has not yet answered it.

    Everything the interface needs to render the question, and nothing that would let a student
    reverse-engineer the grade: no ideal answer, no expected concepts, no common mistakes, no
    rubric. Adding any of those here would silently defeat the assessment.
    """

    id: uuid.UUID = Field(description="Question ID.")
    question_version_id: uuid.UUID = Field(
        description="Version this presentation came from; recorded with the attempt."
    )
    category_slug: str
    category_name: str
    subcategory: str | None = None
    difficulty: int = Field(ge=1, le=5, description="Difficulty from 1 to 5.")
    prompt: str = Field(description="The question text shown to the student.")


class QuestionWithAnswerResponse(QuestionForAnsweringResponse):
    """A question including its ideal answer, for review after the student has submitted.

    Only ever returned for a question the caller has already answered. The ideal answer is
    teaching material once an answer exists; before that it is the answer key.
    """

    ideal_answer: str = Field(description="Model answer, revealed only after submission.")


# --------------------------------------------------------------------------------------
# Admin-facing
# --------------------------------------------------------------------------------------


class QuestionVersionResponse(BaseModel):
    """A question version including all grading content. Administrators only."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    question_id: uuid.UUID
    version: int
    status: QuestionVersionStatus
    prompt: str
    ideal_answer: str
    expected_concepts: list[dict[str, Any]]
    common_mistakes: list[dict[str, Any]]
    rubric: dict[str, Any]
    created_by: uuid.UUID | None = None
    created_at: datetime


class QuestionVersionSummaryResponse(BaseModel):
    """A version's identity and lifecycle, without its content, for history listings."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    status: QuestionVersionStatus
    created_by: uuid.UUID | None = None
    created_at: datetime


class AdminQuestionResponse(BaseModel):
    """A question with its administrative metadata. Administrators only."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_key: str | None = None
    category_slug: str
    subcategory: str | None = None
    difficulty: int
    status: QuestionStatus
    created_at: datetime
    updated_at: datetime
    published_version: QuestionVersionSummaryResponse | None = Field(
        default=None, description="The version currently used for grading, if any."
    )
    version_count: int = 0


class AdminQuestionDetailResponse(AdminQuestionResponse):
    """A question with its full version history. Administrators only."""

    versions: list[QuestionVersionSummaryResponse] = Field(default_factory=list)


class AdminQuestionListResponse(BaseModel):
    """A page of questions for the admin list view."""

    items: list[AdminQuestionResponse]
    next_cursor: datetime | None = Field(
        default=None, description="Pass as `before` to fetch the next page; null when exhausted."
    )


class RubricValidationResponse(BaseModel):
    """The result of checking whether a version is complete enough to publish."""

    is_valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CategoryCoverageResponse(BaseModel):
    """How much gradeable content one category holds, against what a diagnostic needs."""

    slug: str
    name: str
    selectable: int = Field(description="Active questions that have a published version.")
    required: int = Field(description="Questions a diagnostic draws from this category.")
    shortfall: int = Field(description="How many more are needed; zero when the category is ready.")


class QuestionBankCoverageResponse(BaseModel):
    """Per-category counts of gradeable questions.

    Answers the question a content owner actually has: is the bank able to compose a diagnostic,
    and where are the gaps?
    """

    categories: list[CategoryCoverageResponse]
    total_selectable: int
    diagnostic_ready: bool = Field(
        description="Whether every category has enough gradeable questions for a diagnostic."
    )
    counts_by_status: dict[str, int] = Field(
        default_factory=dict, description="Question counts by lifecycle state."
    )
