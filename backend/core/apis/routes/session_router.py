"""Diagnostic session endpoints.

Every route operates on a session belonging to the authenticated caller. None of them accepts a
user ID, and an unknown or someone else's session is answered with 404 rather than 403 so IDs
cannot be probed for existence.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from commons.auth import get_current_user
from core import logger
from core.apis.schemas.requests.attempt_request import PracticeStartRequest
from core.apis.schemas.responses.session_response import (
    SessionResultsResponse,
    SessionStateResponse,
)
from core.controllers.session_controller import SessionController
from core.models.user_model import User

session_router = APIRouter()
logging = logger(__name__)


@session_router.post("/v1/diagnostic", response_model=SessionStateResponse)
async def start_diagnostic(user: User = Depends(get_current_user)) -> SessionStateResponse:
    """
    Start the diagnostic, or resume the one already in progress.

    Resuming is the default. A student who closes the tab or loses their connection must find the
    same 24 questions and the answers they already gave, so this is not an error case and does not
    need a separate endpoint — the client calls this and gets whichever applies.

    Returns:
        SessionStateResponse: The session with its ordered questions, and whether it was resumed.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 402: A free account has already used its one diagnostic.
        HTTPException 409: The question bank cannot supply a complete diagnostic.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/diagnostic endpoint")
        controller = SessionController()
        session_row, resumed = await controller.start_diagnostic(user=user)
        state = await controller.get_state(user=user, session_id=session_row.id)
        return SessionStateResponse(**state, resumed=resumed)
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/diagnostic endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/diagnostic endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@session_router.post("/v1/practice", response_model=SessionStateResponse, status_code=201)
async def start_practice(
    request: PracticeStartRequest, user: User = Depends(get_current_user)
) -> SessionStateResponse:
    """
    Compose and start a practice session.

    Always creates a new set, unlike the diagnostic. A student choosing "10 questions on
    Valuation" is asking for a new set, and handing them an older half-finished one would answer a
    different question; any previous practice session is abandoned first.

    Args:
        request: Set size and optional category.
        user: The authenticated caller.

    Returns:
        SessionStateResponse: The new session, its questions, and why it was composed this way.

    Raises:
        HTTPException 400: Unsupported set size, or an unknown category.
        HTTPException 401: Not authenticated.
        HTTPException 402: The free practice allowance is used up.
        HTTPException 409: No questions are available to practise.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/practice endpoint")
        controller = SessionController()
        session_row = await controller.start_practice(
            user=user, size=request.size, category_slug=request.category_slug
        )
        return SessionStateResponse(
            **await controller.get_state(user=user, session_id=session_row.id)
        )
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/practice endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/practice endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@session_router.get("/v1/diagnostic", response_model=SessionStateResponse | None)
async def current_diagnostic(
    user: User = Depends(get_current_user),
) -> SessionStateResponse | None:
    """
    Read the caller's diagnostic without creating one.

    Returns the session in progress, or the most recent finished one, or null. Kept separate from
    the POST because asking "do I have a diagnostic" must not create one as a side effect, which
    is what calling the start endpoint to find out would do.

    Returns:
        SessionStateResponse | None: The diagnostic, or null when the student has never started.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/diagnostic endpoint")
        state = await SessionController().current_diagnostic(user=user)
        return SessionStateResponse(**state) if state else None
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/diagnostic endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/diagnostic endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@session_router.get("/v1/sessions/{session_id}", response_model=SessionStateResponse)
async def get_session(
    session_id: uuid.UUID, user: User = Depends(get_current_user)
) -> SessionStateResponse:
    """
    Read one of the caller's sessions with its questions and progress.

    Args:
        session_id: Session to read.
        user: The authenticated caller.

    Returns:
        SessionStateResponse: Session state and its ordered questions.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: Unknown session, or one the caller does not own.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/sessions/{session_id} endpoint")
        state = await SessionController().get_state(user=user, session_id=session_id)
        return SessionStateResponse(**state)
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/sessions/{{session_id}} endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/sessions/{{session_id}} endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@session_router.post("/v1/sessions/{session_id}/complete", response_model=SessionStateResponse)
async def complete_session(
    session_id: uuid.UUID, user: User = Depends(get_current_user)
) -> SessionStateResponse:
    """
    Finish a session once every question has been answered.

    Completing does not wait for grading. Grading is asynchronous and can outlast a student's
    patience for a spinner; the results endpoint reports grading progress instead.

    Args:
        session_id: Session to complete.
        user: The authenticated caller.

    Returns:
        SessionStateResponse: The completed session.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: Unknown session, or one the caller does not own.
        HTTPException 409: Not every question has been answered.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/sessions/{session_id}/complete endpoint")
        controller = SessionController()
        await controller.complete(user=user, session_id=session_id)
        return SessionStateResponse(**await controller.get_state(user=user, session_id=session_id))
    except HTTPException as httperror:
        logging.error(
            f"Error in POST /v1/sessions/{{session_id}}/complete endpoint: {httperror.detail}"
        )
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/sessions/{{session_id}}/complete endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@session_router.get("/v1/sessions/{session_id}/results", response_model=SessionResultsResponse)
async def get_results(
    session_id: uuid.UUID, user: User = Depends(get_current_user)
) -> SessionResultsResponse:
    """
    Read a finished session's results.

    Polled while grading finishes. Until every attempt has resolved the response carries grading
    progress and no scores at all, because a readiness number computed from half the evidence is
    a wrong number rather than an early one.

    Args:
        session_id: Session to report on.
        user: The authenticated caller.

    Returns:
        SessionResultsResponse: Progress, category results, strengths, weaknesses, next action.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: Unknown session, or one the caller does not own.
        HTTPException 409: The session has not been finished.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/sessions/{session_id}/results endpoint")
        return SessionResultsResponse(
            **await SessionController().results(user=user, session_id=session_id)
        )
    except HTTPException as httperror:
        logging.error(
            f"Error in GET /v1/sessions/{{session_id}}/results endpoint: {httperror.detail}"
        )
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/sessions/{{session_id}}/results endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error
