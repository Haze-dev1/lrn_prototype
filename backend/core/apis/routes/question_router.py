"""Student-facing question and category endpoints.

There is deliberately no `GET /v1/questions/{id}`. A question is only ever reachable through a
session that belongs to the caller, because an endpoint that served any question by ID would let
one signed-in account enumerate the entire bank — which both destroys the assessment and gives
away the product's most expensive asset.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from commons.auth import get_current_user
from core import logger
from core.apis.schemas.responses.question_response import (
    CategoryResponse,
    QuestionForAnsweringResponse,
    QuestionWithAnswerResponse,
)
from core.controllers.question_controller import QuestionController
from core.models.user_model import User

question_router = APIRouter()
logging = logger(__name__)


@question_router.get("/v1/categories", response_model=list[CategoryResponse])
async def list_categories() -> list[CategoryResponse]:
    """
    List the skill categories.

    Public reference data: the taxonomy carries no assessment value and the marketing pages
    display it, so it needs no session.

    Returns:
        list[CategoryResponse]: Categories in display order.

    Raises:
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/categories endpoint")
        categories = await QuestionController().list_categories()
        return [CategoryResponse.model_validate(category) for category in categories]
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/categories endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/categories endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@question_router.get(
    "/v1/sessions/{session_id}/questions/{question_id}",
    response_model=QuestionWithAnswerResponse | QuestionForAnsweringResponse,
)
async def get_session_question(
    session_id: uuid.UUID,
    question_id: uuid.UUID,
    user: User = Depends(get_current_user),
) -> QuestionWithAnswerResponse | QuestionForAnsweringResponse:
    """
    Read one question from a session the caller owns.

    The response type is chosen from whether an attempt already exists, and the two types are
    separate classes rather than one class with an optional field. A response built from
    ``QuestionForAnsweringResponse`` has nowhere to put an ideal answer, so a future change that
    tried to include one would fail validation instead of leaking the answer key.

    Args:
        session_id: Session the question is served from.
        question_id: Question requested.
        user: The authenticated caller.

    Returns:
        QuestionWithAnswerResponse | QuestionForAnsweringResponse: The question, with the ideal
        answer included only once the caller has submitted an answer to it.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: Unknown session, a session the caller does not own, or a question that
            is not part of it.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/sessions/{session_id}/questions/{question_id} endpoint")
        payload = await QuestionController().get_for_session(
            user=user, session_id=session_id, question_id=question_id
        )
        if "ideal_answer" in payload:
            return QuestionWithAnswerResponse(**payload)
        return QuestionForAnsweringResponse(**payload)
    except HTTPException as httperror:
        logging.error(
            f"Error in GET /v1/sessions/{{session_id}}/questions/{{question_id}} endpoint: "
            f"{httperror.detail}"
        )
        raise httperror
    except Exception as error:
        logging.error(
            f"Error in GET /v1/sessions/{{session_id}}/questions/{{question_id}} endpoint: {error}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error
