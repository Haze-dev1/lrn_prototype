"""Request schemas for question and version management."""

from typing import Any

from pydantic import BaseModel, Field, field_validator

from core.constants.enums import QuestionStatus

MAX_PROMPT_LENGTH = 4000
MAX_IDEAL_ANSWER_LENGTH = 8000
MAX_CONCEPTS = 25


class ConceptEntry(BaseModel):
    """One expected concept or common mistake.

    The key is a stable identifier the grader returns and the interface groups by; the label is
    what a student reads. Keeping them separate means the wording can be improved without
    invalidating the concept history already recorded against past attempts.
    """

    key: str = Field(min_length=1, max_length=64, description="Stable identifier.")
    label: str = Field(min_length=1, max_length=200, description="Human-readable description.")

    @field_validator("key")
    @classmethod
    def _normalise_key(cls, value: str) -> str:
        """
        Normalise a concept key to lowercase snake case.

        Keys are compared across versions and attempts, so 'Net Debt' and 'net_debt' must not
        become two different concepts in a student's history.

        Args:
            value: The submitted key.

        Returns:
            str: The normalised key.
        """
        return value.strip().lower().replace(" ", "_").replace("-", "_")


class QuestionCreateRequest(BaseModel):
    """Payload creating a question's identity and taxonomy.

    A first version may be supplied inline. Authoring a question and its content are one action
    for a content owner, and splitting them across two requests would leave an empty question
    behind whenever the second one failed.
    """

    category_slug: str = Field(min_length=1, max_length=100)
    subcategory: str | None = Field(default=None, max_length=200)
    difficulty: int = Field(ge=1, le=5)
    source_key: str | None = Field(
        default=None,
        max_length=120,
        description="Stable key for authored content, used to re-seed without duplicating.",
    )
    initial_version: "QuestionVersionCreateRequest | None" = Field(
        default=None, description="Optional first version, created with the question."
    )


class QuestionUpdateRequest(BaseModel):
    """Payload editing a question's taxonomy. Grading content lives in versions."""

    category_slug: str | None = Field(default=None, min_length=1, max_length=100)
    subcategory: str | None = Field(default=None, max_length=200)
    difficulty: int | None = Field(default=None, ge=1, le=5)


class QuestionStatusRequest(BaseModel):
    """Payload changing a question's lifecycle state."""

    status: QuestionStatus


class QuestionVersionCreateRequest(BaseModel):
    """Payload creating a new version of a question's grading content.

    Creating a version never edits a published one, so every historical attempt stays
    attributable to the rubric it was actually graded against.

    Concept lists are bounded here as well as in the rubric validator. The validator explains a
    content problem to an author; these bounds stop an oversized payload reaching the database at
    all, which is a different job and belongs at the edge.
    """

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_LENGTH)
    ideal_answer: str = Field(min_length=1, max_length=MAX_IDEAL_ANSWER_LENGTH)
    expected_concepts: list[ConceptEntry] = Field(default_factory=list, max_length=MAX_CONCEPTS)
    common_mistakes: list[ConceptEntry] = Field(default_factory=list, max_length=MAX_CONCEPTS)
    rubric: dict[str, Any] = Field(default_factory=dict)
    publish: bool = Field(
        default=False,
        description="Publish immediately. Rejected if the rubric is incomplete.",
    )


class QuestionVersionUpdateRequest(BaseModel):
    """Payload editing a draft version in place.

    Accepted only for DRAFT versions; the API rejects an edit to a published or superseded one.
    A draft has never graded an attempt, so editing it cannot change the meaning of a past score,
    and forcing a new version for every typo would bury real rubric history in editing noise.
    """

    prompt: str | None = Field(default=None, min_length=1, max_length=MAX_PROMPT_LENGTH)
    ideal_answer: str | None = Field(default=None, min_length=1, max_length=MAX_IDEAL_ANSWER_LENGTH)
    expected_concepts: list[ConceptEntry] | None = Field(default=None, max_length=MAX_CONCEPTS)
    common_mistakes: list[ConceptEntry] | None = Field(default=None, max_length=MAX_CONCEPTS)
    rubric: dict[str, Any] | None = None


# QuestionCreateRequest refers to QuestionVersionCreateRequest before it is defined, so the
# forward reference is resolved here rather than leaving every caller to remember to do it.
QuestionCreateRequest.model_rebuild()
