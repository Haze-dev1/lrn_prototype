"""Student-facing question access.

The only way a student reaches a question is through a session that belongs to them. There is
deliberately no endpoint that fetches an arbitrary question by ID: that would let any signed-in
account walk the entire bank, which both destroys the assessment and gives away the product's
most expensive asset.
"""

import uuid

from fastapi import HTTPException, status

from core import logger
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.category_crud import CRUDCategory
from core.cruds.question_crud import CRUDQuestion, CRUDQuestionVersion
from core.cruds.session_crud import CRUDSession
from core.models.user_model import User

logging = logger(__name__)


class QuestionController:
    """Serves questions to students in the protected, answer-free shape."""

    def __init__(self) -> None:
        """Initialise the controller with the CRUD layers it coordinates."""
        self.CRUDQuestion = CRUDQuestion()
        self.CRUDQuestionVersion = CRUDQuestionVersion()
        self.CRUDCategory = CRUDCategory()
        self.CRUDSession = CRUDSession()
        self.CRUDAttempt = CRUDAttempt()

    async def list_categories(self) -> list:
        """
        Read the skill categories.

        Public reference data with no assessment value, used to label progress and practice.

        Returns:
            list: Categories in display order.

        Raises:
            HTTPException 500: Unexpected failure reading categories.
        """
        try:
            logging.info("Executing QuestionController.list_categories")
            return await self.CRUDCategory.list_all()
        except Exception as error:
            logging.error(f"Error in QuestionController.list_categories: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal Server Error",
            ) from error

    async def get_for_session(
        self, *, user: User, session_id: uuid.UUID, question_id: uuid.UUID
    ) -> dict:
        """
        Read one question of a session the caller owns, in the protected shape.

        Enforces three things in order: the session exists, it belongs to the caller, and the
        question is actually part of it. A 404 is returned for another user's session rather than
        a 403, so session IDs cannot be probed for existence.

        The ideal answer is included only once the caller has already submitted an answer to this
        question. Before that it is the answer key; after that it is teaching material.

        Args:
            user: The authenticated caller.
            session_id: Session the question is being served from.
            question_id: Question requested.

        Returns:
            dict: Question fields, with `ideal_answer` present only after submission.

        Raises:
            HTTPException 404: Unknown session, a session the caller does not own, or a question
                that is not part of it.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing QuestionController.get_for_session")
            session = await self.CRUDSession.get_with_questions(session_id=session_id)
            if session is None or session.user_id != user.id:
                logging.warning(
                    f"User {user.id} requested a question from session {session_id} "
                    f"they do not own or that does not exist"
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
                )

            slot = next(
                (item for item in session.questions if item.question_id == question_id), None
            )
            if slot is None:
                logging.warning(f"Question {question_id} is not part of session {session_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Question not found"
                )

            question = await self.CRUDQuestion.get_by_id(question_id=question_id)
            version = await self.CRUDQuestionVersion.get_by_id(version_id=slot.question_version_id)
            if question is None or version is None:
                logging.error(f"Session {session_id} references a missing question or version")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Question not found"
                )

            category = await self.CRUDCategory.get_by_slug(slug=question.category_slug)
            payload = {
                "id": question.id,
                "question_version_id": version.id,
                "category_slug": question.category_slug,
                "category_name": category.name if category else question.category_slug,
                "subcategory": question.subcategory,
                "difficulty": question.difficulty,
                "prompt": version.prompt,
            }

            existing_attempt = await self.CRUDAttempt.get_for_session_question(
                session_id=session_id, question_id=question_id
            )
            if existing_attempt is not None:
                payload["ideal_answer"] = version.ideal_answer

            return payload
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in QuestionController.get_for_session: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal Server Error",
            ) from error
