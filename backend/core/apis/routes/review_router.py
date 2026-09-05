"""Review history, grade disputes, and progress endpoints.

Every route reads or writes the authenticated caller's own record. None accepts a user ID, and an
attempt belonging to someone else is answered with 404 rather than 403.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from commons.auth import get_current_user
from core import logger
from core.apis.schemas.responses.review_response import (
    GradeFlagRequest,
    GradeFlagResponse,
    ProgressResponse,
    ReviewListResponse,
)
from core.controllers.review_controller import ReviewController
from core.models.user_model import User

review_router = APIRouter()
logging = logger(__name__)


@review_router.get("/v1/review", response_model=ReviewListResponse)
async def list_review(
    category_slug: str | None = Query(default=None, max_length=100),
    max_score: int | None = Query(default=None, ge=0, le=100),
    missed_concept: str | None = Query(default=None, max_length=64),
    flagged_only: bool = Query(default=False),
    recent_only: bool = Query(default=False),
    before: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(get_current_user),
) -> ReviewListResponse:
    """
    List the caller's graded attempts, filtered.

    The filters are the ones that make an answer worth revisiting — a category, a low score, a
    specific concept missed, a disputed grade, recency — rather than date alone.

    Args:
        category_slug: Restrict to one category.
        max_score: Only attempts scoring at or below this.
        missed_concept: Only attempts that missed this concept.
        flagged_only: Only attempts the caller disputed.
        recent_only: Only attempts from the recent window.
        before: Keyset cursor from a previous page.
        limit: Page size.
        user: The authenticated caller.

    Returns:
        ReviewListResponse: A page of history and the cursor for the next.

    Raises:
        HTTPException 400: Unknown category.
        HTTPException 401: Not authenticated.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/review endpoint")
        page = await ReviewController().list_attempts(
            user=user,
            category_slug=category_slug,
            max_score=max_score,
            missed_concept=missed_concept,
            flagged_only=flagged_only,
            recent_only=recent_only,
            before=before,
            limit=limit,
        )
        return ReviewListResponse(**page)
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/review endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/review endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@review_router.post(
    "/v1/attempts/{attempt_id}/flag",
    response_model=GradeFlagResponse,
    status_code=status.HTTP_201_CREATED,
)
async def flag_grade(
    attempt_id: uuid.UUID,
    request: GradeFlagRequest,
    user: User = Depends(get_current_user),
) -> GradeFlagResponse:
    """
    Dispute one of the caller's own grades.

    A flag is a statement, not a vote: raising it twice returns the existing one rather than
    stacking. Flags are a quality signal on the question bank as much as a support channel — a
    cluster of them on one question usually means the rubric is wrong, not that the students are.

    Args:
        attempt_id: The attempt whose grade is disputed.
        request: Reason and optional comment.
        user: The authenticated caller.

    Returns:
        GradeFlagResponse: The flag's identity and status.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: No such attempt, or it belongs to another user.
        HTTPException 409: The attempt has not been graded.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/attempts/{attempt_id}/flag endpoint")
        flag = await ReviewController().flag_grade(
            user=user,
            attempt_id=attempt_id,
            reason=request.reason.value,
            comment=request.comment,
        )
        return GradeFlagResponse(**flag)
    except HTTPException as httperror:
        logging.error(
            f"Error in POST /v1/attempts/{{attempt_id}}/flag endpoint: {httperror.detail}"
        )
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/attempts/{{attempt_id}}/flag endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@review_router.get("/v1/progress", response_model=ProgressResponse)
async def get_progress(user: User = Depends(get_current_user)) -> ProgressResponse:
    """
    Read the caller's mastery across every category, with their trend.

    Returns:
        ProgressResponse: Per-category mastery, the weekly trend, and headline figures.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/progress endpoint")
        return ProgressResponse(**await ReviewController().progress(user=user))
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/progress endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/progress endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error
