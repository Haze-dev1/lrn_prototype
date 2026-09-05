"""Helpers for building valid domain rows in tests.

Each helper creates the minimum valid record and lets a test override only the field under
examination, so a test's intent stays visible instead of being buried in setup.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from core.constants.enums import (
    GradingStatus,
    QuestionStatus,
    SessionStatus,
    SessionType,
)
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.question_crud import CRUDQuestion, CRUDQuestionVersion
from core.cruds.session_crud import CRUDSession
from core.cruds.user_crud import CRUDUser
from core.models.attempt_model import Attempt
from core.models.question_model import Question, QuestionVersion
from core.models.session_model import Session
from core.models.user_model import User

DEFAULT_CATEGORY = "valuation"


async def make_user(**overrides: Any) -> User:
    """
    Create a user with a unique email.

    Args:
        **overrides: Fields to override on the default user.

    Returns:
        User: The created user.
    """
    data: dict[str, Any] = {
        "email": f"student-{uuid.uuid4().hex[:12]}@example.edu",
        "password_hash": "argon2-placeholder-hash",
    }
    data.update(overrides)
    return await CRUDUser().create(obj_in=data)


async def make_question(**overrides: Any) -> Question:
    """
    Create an active question.

    Args:
        **overrides: Fields to override on the default question.

    Returns:
        Question: The created question.
    """
    data: dict[str, Any] = {
        "category_slug": DEFAULT_CATEGORY,
        "difficulty": 2,
        "status": QuestionStatus.ACTIVE,
    }
    data.update(overrides)
    return await CRUDQuestion().create(obj_in=data)


async def make_question_version(
    *, question_id: uuid.UUID, published: bool = True, **overrides: Any
) -> QuestionVersion:
    """
    Create a question version with a complete rubric.

    Args:
        question_id: Owning question ID.
        published: Whether to publish the version after creating it.
        **overrides: Fields to override on the default version.

    Returns:
        QuestionVersion: The created version.
    """
    data: dict[str, Any] = {
        "question_id": question_id,
        "prompt": "Walk me through how you get from enterprise value to equity value.",
        "ideal_answer": "Subtract net debt: start from enterprise value, subtract total debt, "
        "add back cash and equivalents, and adjust for minority interest and preferred stock.",
        "expected_concepts": [
            {"key": "net_debt", "label": "Net debt adjustment"},
            {"key": "cash", "label": "Treatment of cash equivalents"},
        ],
        "common_mistakes": [{"key": "double_count_debt", "label": "Double-counting debt"}],
        "rubric": {"scoring": "concept coverage", "weight": 1},
    }
    data.update(overrides)
    version = await CRUDQuestionVersion().create(obj_in=data)
    if published:
        published_version = await CRUDQuestionVersion().publish(version_id=version.id)
        assert published_version is not None
        return published_version
    return version


async def make_gradeable_question() -> tuple[Question, QuestionVersion]:
    """
    Create an active question together with a published version.

    Returns:
        tuple[Question, QuestionVersion]: The question and its published version.
    """
    question = await make_question()
    version = await make_question_version(question_id=question.id)
    return question, version


async def make_session(
    *, user_id: uuid.UUID, questions: list[dict[str, Any]] | None = None, **overrides: Any
) -> Session:
    """
    Create a session with its question composition.

    Args:
        user_id: Owning user ID.
        questions: Composition rows; one is generated when omitted.
        **overrides: Fields to override on the default session.

    Returns:
        Session: The created session.
    """
    if questions is None:
        question, version = await make_gradeable_question()
        questions = [{"position": 0, "question_id": question.id, "question_version_id": version.id}]

    data: dict[str, Any] = {
        "user_id": user_id,
        "type": SessionType.PRACTICE,
        "status": SessionStatus.IN_PROGRESS,
        "question_count": len(questions),
    }
    data.update(overrides)
    return await CRUDSession().create_with_questions(obj_in=data, questions=questions)


async def make_attempt(
    *,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    question_id: uuid.UUID,
    question_version_id: uuid.UUID,
    **overrides: Any,
) -> Attempt:
    """
    Create an ungraded attempt.

    Args:
        user_id: Owning user ID.
        session_id: Session the attempt belongs to.
        question_id: Question answered.
        question_version_id: Version graded against.
        **overrides: Fields to override on the default attempt.

    Returns:
        Attempt: The created attempt.
    """
    data: dict[str, Any] = {
        "user_id": user_id,
        "session_id": session_id,
        "question_id": question_id,
        "question_version_id": question_version_id,
        "answer": "Enterprise value less net debt gives equity value.",
        "grading_status": GradingStatus.PENDING,
    }
    data.update(overrides)
    return await CRUDAttempt().create(obj_in=data)


def graded_result(score: int = 82, band: str = "strong") -> dict[str, Any]:
    """
    Build a validated grade payload for use with ``CRUDAttempt.set_grade_result``.

    Args:
        score: Numeric score, 0-100.
        band: Qualitative band.

    Returns:
        dict[str, Any]: Grade fields ready to persist.
    """
    return {
        "score": score,
        "band": band,
        "feedback": "You covered the net debt bridge but did not address cash equivalents.",
        "concepts_hit": ["net_debt"],
        "concepts_missed": ["cash"],
        "mistake_flags": [],
    }


def utc_now() -> datetime:
    """
    Return the current UTC time.

    Returns:
        datetime: Timezone-aware current time.
    """
    return datetime.now(UTC)
