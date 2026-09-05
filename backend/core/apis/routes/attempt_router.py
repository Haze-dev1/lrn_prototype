"""Answer submission and grade retrieval endpoints.

Submission returns as soon as the answer is stored and hands grading to a background task. The
alternative — grading inline and returning the finished grade — would hold the request open for
however long a model takes, put the student's answer at the mercy of an HTTP timeout, and give
the interface nothing to show for ten seconds. Here the answer is safe immediately, the client
polls, and the scheduled sweep finishes anything the background task does not.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response, status

from commons.auth import get_current_user
from core import logger
from core.apis.schemas.requests.attempt_request import AttemptSubmitRequest
from core.apis.schemas.responses.attempt_response import (
    AttemptStateResponse,
    AttemptSubmittedResponse,
    GradedAttemptResponse,
)
from core.controllers.attempt_controller import AttemptController
from core.models.user_model import User
from core.services.ai.grading_service import GradingService

attempt_router = APIRouter()
logging = logger(__name__)


async def _grade_in_background(attempt_id: uuid.UUID) -> None:
    """
    Grade one attempt outside the request cycle.

    Swallows every exception on purpose. This runs after the response has been sent, so raising
    would only produce an unhandled-task warning in the logs and lose the reason. The grading
    service already records its own failures and leaves the attempt in a state the retry sweep
    reclaims, so the answer is safe either way.

    Args:
        attempt_id: The attempt to grade.
    """
    try:
        await GradingService().grade_attempt(attempt_id=attempt_id)
    except Exception as error:
        logging.error(f"Background grading failed for attempt {attempt_id}: {error}")


@attempt_router.post(
    "/v1/sessions/{session_id}/attempts",
    response_model=AttemptSubmittedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_attempt(
    session_id: uuid.UUID,
    request: AttemptSubmitRequest,
    background_tasks: BackgroundTasks,
    response: Response,
    user: User = Depends(get_current_user),
) -> AttemptSubmittedResponse:
    """
    Submit an answer to one question of the caller's session.

    Resubmitting the same question returns the original attempt with **200** and
    ``duplicate: true`` rather than creating a second one, so a double click or a client retry
    cannot produce two grades or two paid model calls.

    Args:
        session_id: Session the answer belongs to.
        request: Question ID, answer text, and optional timing.
        background_tasks: Runs grading after the response is sent.
        response: Used to downgrade the status code for a duplicate submission.
        user: The authenticated caller.

    Returns:
        AttemptSubmittedResponse: The stored attempt and its grading state.

    Raises:
        HTTPException 400: The question ID is not a valid identifier.
        HTTPException 401: Not authenticated.
        HTTPException 402: Today's free grading allowance is used up.
        HTTPException 404: Unknown session, a session the caller does not own, or a question that
            is not part of it.
        HTTPException 409: The session is no longer accepting answers.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/sessions/{session_id}/attempts endpoint")
        attempt, duplicate = await AttemptController().submit(
            user=user, session_id=session_id, payload=request.model_dump()
        )
        if duplicate:
            response.status_code = status.HTTP_200_OK
        else:
            background_tasks.add_task(_grade_in_background, attempt.id)

        return AttemptSubmittedResponse(
            **AttemptStateResponse.model_validate(attempt).model_dump(), duplicate=duplicate
        )
    except HTTPException as httperror:
        logging.error(
            f"Error in POST /v1/sessions/{{session_id}}/attempts endpoint: {httperror.detail}"
        )
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/sessions/{{session_id}}/attempts endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@attempt_router.get(
    "/v1/attempts/{attempt_id}",
    response_model=GradedAttemptResponse | AttemptStateResponse,
)
async def get_attempt(
    attempt_id: uuid.UUID, user: User = Depends(get_current_user)
) -> GradedAttemptResponse | AttemptStateResponse:
    """
    Read one of the caller's attempts, with its grade once grading has finished.

    Polled by the interface while an answer is being graded. The two response types are separate
    classes rather than one with optional fields: an ungraded attempt is rendered from a type that
    has nowhere to put a score, so a pending grade cannot surface as a zero.

    Args:
        attempt_id: Attempt to read.
        user: The authenticated caller.

    Returns:
        GradedAttemptResponse | AttemptStateResponse: The grade, or the grading state.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: No such attempt, or it belongs to another user.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/attempts/{attempt_id} endpoint")
        payload = await AttemptController().get(user=user, attempt_id=attempt_id)
        if "score" in payload:
            return GradedAttemptResponse(**payload)
        return AttemptStateResponse(**payload)
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/attempts/{{attempt_id}} endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/attempts/{{attempt_id}} endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error
