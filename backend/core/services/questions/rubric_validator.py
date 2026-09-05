"""Rubric completeness validation.

A question with an incomplete rubric does not fail loudly at grading time — it produces a
confidently wrong grade, which is the worst possible failure for this product. Validation
therefore runs before a version can be published, and reports every problem at once so a content
author fixes them in one pass rather than discovering them one at a time.

The database enforces the same core rules as CHECK constraints. That redundancy is deliberate:
this layer explains *what* is wrong to a human, the constraint guarantees it can never be stored.
"""

from dataclasses import dataclass, field
from typing import Any

from core import logger

logging = logger(__name__)

MIN_PROMPT_LENGTH = 20
MIN_IDEAL_ANSWER_LENGTH = 40
MIN_EXPECTED_CONCEPTS = 2
MAX_EXPECTED_CONCEPTS = 12
MAX_COMMON_MISTAKES = 12


@dataclass
class RubricValidationResult:
    """Outcome of validating a question version's grading content."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _validate_labelled_items(
    items: Any, *, field_name: str, minimum: int, maximum: int, errors: list[str]
) -> None:
    """
    Validate a list of ``{key, label}`` rubric entries.

    Keys are what the grader returns and what the interface groups a student's misses by, so a
    duplicate or missing key silently corrupts the concept-level feedback that the whole product
    is built on.

    Args:
        items: The value to validate.
        field_name: Field name, used in error messages.
        minimum: Minimum number of entries required.
        maximum: Maximum number of entries permitted.
        errors: List that validation failures are appended to.
    """
    if not isinstance(items, list):
        errors.append(f"{field_name} must be a list")
        return

    if len(items) < minimum:
        errors.append(f"{field_name} needs at least {minimum} entries, found {len(items)}")
    if len(items) > maximum:
        errors.append(f"{field_name} has {len(items)} entries, more than the maximum of {maximum}")

    seen_keys: set[str] = set()
    for index, item in enumerate(items):
        position = f"{field_name}[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{position} must be an object with 'key' and 'label'")
            continue

        key = item.get("key")
        label = item.get("label")
        if not isinstance(key, str) or not key.strip():
            errors.append(f"{position} is missing a non-empty 'key'")
        elif key in seen_keys:
            errors.append(f"{position} repeats the key '{key}'")
        else:
            seen_keys.add(key)

        if not isinstance(label, str) or not label.strip():
            errors.append(f"{position} is missing a non-empty 'label'")


def validate_rubric(version_data: dict[str, Any]) -> RubricValidationResult:
    """
    Check whether a question version carries everything needed to grade an answer.

    Errors block publication. Warnings do not: they flag content that will grade, but probably
    not as well as it should, and a content author needs to be able to see the difference.

    Args:
        version_data: Version fields — prompt, ideal answer, expected concepts, common mistakes.

    Returns:
        RubricValidationResult: Validity, blocking errors, and non-blocking warnings.
    """
    logging.info("Executing validate_rubric")
    errors: list[str] = []
    warnings: list[str] = []

    prompt = version_data.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append("prompt is required")
    elif len(prompt.strip()) < MIN_PROMPT_LENGTH:
        errors.append(f"prompt must be at least {MIN_PROMPT_LENGTH} characters")

    ideal_answer = version_data.get("ideal_answer")
    if not isinstance(ideal_answer, str) or not ideal_answer.strip():
        errors.append("ideal_answer is required")
    elif len(ideal_answer.strip()) < MIN_IDEAL_ANSWER_LENGTH:
        errors.append(f"ideal_answer must be at least {MIN_IDEAL_ANSWER_LENGTH} characters")

    _validate_labelled_items(
        version_data.get("expected_concepts"),
        field_name="expected_concepts",
        minimum=MIN_EXPECTED_CONCEPTS,
        maximum=MAX_EXPECTED_CONCEPTS,
        errors=errors,
    )

    common_mistakes = version_data.get("common_mistakes", [])
    if common_mistakes:
        _validate_labelled_items(
            common_mistakes,
            field_name="common_mistakes",
            minimum=0,
            maximum=MAX_COMMON_MISTAKES,
            errors=errors,
        )
    else:
        # Not blocking: a question can be graded on concept coverage alone. But the named-mistake
        # feedback is a large part of what makes a grade feel specific rather than generic.
        warnings.append(
            "No common mistakes defined; grades for this question will not name specific errors"
        )

    rubric = version_data.get("rubric")
    if rubric is not None and not isinstance(rubric, dict):
        errors.append("rubric must be an object")

    if errors:
        logging.warning(f"Rubric validation failed with {len(errors)} errors")

    return RubricValidationResult(is_valid=not errors, errors=errors, warnings=warnings)
