"""Administrative question bank endpoints.

Every route depends on ``require_admin``, which returns 404 rather than 403 for a signed-in
non-administrator: a 403 would confirm that these endpoints exist, and the admin surface is not
something an ordinary account should be able to map.

Responses here intentionally carry rubrics and ideal answers. That is the whole point of the
surface, and it is why the authorisation dependency is declared on the router rather than route
by route — a new endpoint added below cannot be left unprotected by omission.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from commons.auth import require_admin
from core import logger
from core.apis.schemas.requests.question_request import (
    QuestionCreateRequest,
    QuestionStatusRequest,
    QuestionUpdateRequest,
    QuestionVersionCreateRequest,
    QuestionVersionUpdateRequest,
)
from core.apis.schemas.responses.question_response import (
    AdminQuestionDetailResponse,
    AdminQuestionListResponse,
    QuestionBankCoverageResponse,
    QuestionVersionResponse,
    RubricValidationResponse,
)
from core.constants.enums import QuestionStatus
from core.controllers.admin_question_controller import AdminQuestionController
from core.models.user_model import User

admin_question_router = APIRouter(prefix="/v1/admin", dependencies=[Depends(require_admin)])
logging = logger(__name__)


@admin_question_router.get("/questions", response_model=AdminQuestionListResponse)
async def list_questions(
    category_slug: str | None = Query(default=None, max_length=100),
    question_status: QuestionStatus | None = Query(default=None, alias="status"),
    difficulty: int | None = Query(default=None, ge=1, le=5),
    search: str | None = Query(default=None, max_length=200),
    before: datetime | None = Query(
        default=None, description="Keyset cursor from a previous page's next_cursor."
    ),
    limit: int = Query(default=50, ge=1, le=100),
) -> AdminQuestionListResponse:
    """
    List questions for content management, filtered and paginated.

    Args:
        category_slug: Restrict to one category.
        question_status: Restrict to one lifecycle state.
        difficulty: Restrict to one difficulty level.
        search: Free-text match on subcategory, source key, or prompt.
        before: Keyset cursor; returns questions created before this timestamp.
        limit: Page size.

    Returns:
        AdminQuestionListResponse: A page of questions and the cursor for the next.

    Raises:
        HTTPException 400: Unknown category or lifecycle state.
        HTTPException 401: Not authenticated.
        HTTPException 404: The caller is not an administrator.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/admin/questions endpoint")
        page = await AdminQuestionController().list_questions(
            category_slug=category_slug,
            question_status=question_status.value if question_status else None,
            difficulty=difficulty,
            search=search,
            before=before,
            limit=limit,
        )
        return AdminQuestionListResponse(**page)
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/admin/questions endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/admin/questions endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@admin_question_router.get("/questions/coverage", response_model=QuestionBankCoverageResponse)
async def question_bank_coverage() -> QuestionBankCoverageResponse:
    """
    Report gradeable question counts per category and diagnostic readiness.

    Declared above the `/questions/{question_id}` route so the literal path is matched first;
    otherwise 'coverage' would be parsed as a question ID and rejected as a malformed UUID.

    Returns:
        QuestionBankCoverageResponse: Per-category counts and readiness.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: The caller is not an administrator.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/admin/questions/coverage endpoint")
        return QuestionBankCoverageResponse(**await AdminQuestionController().coverage())
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/admin/questions/coverage endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/admin/questions/coverage endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@admin_question_router.post(
    "/questions",
    response_model=AdminQuestionDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_question(
    request: QuestionCreateRequest, admin: User = Depends(require_admin)
) -> AdminQuestionDetailResponse:
    """
    Create a question, optionally with its first version.

    Args:
        request: Taxonomy fields and an optional initial version.
        admin: The acting administrator, recorded as the version author.

    Returns:
        AdminQuestionDetailResponse: The created question with its version history.

    Raises:
        HTTPException 400: Unknown category.
        HTTPException 401: Not authenticated.
        HTTPException 404: The caller is not an administrator.
        HTTPException 422: An inline version was marked for publication but is incomplete.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/admin/questions endpoint")
        question = await AdminQuestionController().create_question(
            admin=admin, payload=request.model_dump()
        )
        return AdminQuestionDetailResponse(**question)
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/admin/questions endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/admin/questions endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@admin_question_router.get("/questions/{question_id}", response_model=AdminQuestionDetailResponse)
async def get_question(question_id: uuid.UUID) -> AdminQuestionDetailResponse:
    """
    Read one question with its full version history.

    Args:
        question_id: Question ID.

    Returns:
        AdminQuestionDetailResponse: The question and its versions, newest first.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: No such question, or the caller is not an administrator.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/admin/questions/{question_id} endpoint")
        question = await AdminQuestionController().get_question(question_id=question_id)
        return AdminQuestionDetailResponse(**question)
    except HTTPException as httperror:
        logging.error(
            f"Error in GET /v1/admin/questions/{{question_id}} endpoint: {httperror.detail}"
        )
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/admin/questions/{{question_id}} endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@admin_question_router.patch("/questions/{question_id}", response_model=AdminQuestionDetailResponse)
async def update_question(
    question_id: uuid.UUID, request: QuestionUpdateRequest
) -> AdminQuestionDetailResponse:
    """
    Update a question's taxonomy. Grading content is changed by creating a version.

    Args:
        question_id: Question ID.
        request: Partial taxonomy payload.

    Returns:
        AdminQuestionDetailResponse: The updated question with its version history.

    Raises:
        HTTPException 400: No fields supplied, or an unknown category.
        HTTPException 401: Not authenticated.
        HTTPException 404: No such question, or the caller is not an administrator.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling PATCH /v1/admin/questions/{question_id} endpoint")
        question = await AdminQuestionController().update_question(
            question_id=question_id, payload=request.model_dump(exclude_unset=True)
        )
        return AdminQuestionDetailResponse(**question)
    except HTTPException as httperror:
        logging.error(
            f"Error in PATCH /v1/admin/questions/{{question_id}} endpoint: {httperror.detail}"
        )
        raise httperror
    except Exception as error:
        logging.error(f"Error in PATCH /v1/admin/questions/{{question_id}} endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@admin_question_router.put(
    "/questions/{question_id}/status", response_model=AdminQuestionDetailResponse
)
async def set_question_status(
    question_id: uuid.UUID, request: QuestionStatusRequest
) -> AdminQuestionDetailResponse:
    """
    Activate or retire a question.

    Args:
        question_id: Question ID.
        request: Target lifecycle state.

    Returns:
        AdminQuestionDetailResponse: The updated question with its version history.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: No such question, or the caller is not an administrator.
        HTTPException 409: Activation requested for a question with no published version.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling PUT /v1/admin/questions/{question_id}/status endpoint")
        question = await AdminQuestionController().set_status(
            question_id=question_id, new_status=request.status
        )
        return AdminQuestionDetailResponse(**question)
    except HTTPException as httperror:
        logging.error(
            f"Error in PUT /v1/admin/questions/{{question_id}}/status endpoint: {httperror.detail}"
        )
        raise httperror
    except Exception as error:
        logging.error(f"Error in PUT /v1/admin/questions/{{question_id}}/status endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@admin_question_router.post(
    "/questions/{question_id}/versions",
    response_model=QuestionVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_version(
    question_id: uuid.UUID,
    request: QuestionVersionCreateRequest,
    admin: User = Depends(require_admin),
) -> QuestionVersionResponse:
    """
    Create a new version of a question's grading content.

    Args:
        question_id: Question the version belongs to.
        request: Version content and whether to publish immediately.
        admin: The acting administrator, recorded as the author.

    Returns:
        QuestionVersionResponse: The created version.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: No such question, or the caller is not an administrator.
        HTTPException 422: Publication was requested and the rubric is incomplete.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/admin/questions/{question_id}/versions endpoint")
        version = await AdminQuestionController().create_version(
            admin=admin, question_id=question_id, payload=request.model_dump()
        )
        return QuestionVersionResponse.model_validate(version)
    except HTTPException as httperror:
        logging.error(
            f"Error in POST /v1/admin/questions/{{question_id}}/versions endpoint: "
            f"{httperror.detail}"
        )
        raise httperror
    except Exception as error:
        logging.error(
            f"Error in POST /v1/admin/questions/{{question_id}}/versions endpoint: {error}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@admin_question_router.get(
    "/questions/{question_id}/versions/{version_id}", response_model=QuestionVersionResponse
)
async def get_version(question_id: uuid.UUID, version_id: uuid.UUID) -> QuestionVersionResponse:
    """
    Read one version in full, including its grading content.

    Args:
        question_id: Question the version must belong to.
        version_id: Version ID.

    Returns:
        QuestionVersionResponse: The version with all grading content.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: No such version on this question, or the caller is not an
            administrator.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/admin/questions/{question_id}/versions/{version_id} endpoint")
        version = await AdminQuestionController().get_version(
            question_id=question_id, version_id=version_id
        )
        return QuestionVersionResponse.model_validate(version)
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/admin/questions versions endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/admin/questions versions endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@admin_question_router.patch(
    "/questions/{question_id}/versions/{version_id}", response_model=QuestionVersionResponse
)
async def update_version(
    question_id: uuid.UUID, version_id: uuid.UUID, request: QuestionVersionUpdateRequest
) -> QuestionVersionResponse:
    """
    Edit a draft version in place. Published and superseded versions are immutable.

    Args:
        question_id: Question the version must belong to.
        version_id: Version to edit.
        request: Partial content payload.

    Returns:
        QuestionVersionResponse: The updated draft.

    Raises:
        HTTPException 400: No fields supplied.
        HTTPException 401: Not authenticated.
        HTTPException 404: No such version on this question, or the caller is not an
            administrator.
        HTTPException 409: The version is published or superseded.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info(
            "Calling PATCH /v1/admin/questions/{question_id}/versions/{version_id} endpoint"
        )
        version = await AdminQuestionController().update_version(
            question_id=question_id,
            version_id=version_id,
            payload=request.model_dump(exclude_unset=True),
        )
        return QuestionVersionResponse.model_validate(version)
    except HTTPException as httperror:
        logging.error(f"Error in PATCH /v1/admin/questions versions endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in PATCH /v1/admin/questions versions endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@admin_question_router.post(
    "/questions/{question_id}/versions/{version_id}/publish",
    response_model=QuestionVersionResponse,
)
async def publish_version(question_id: uuid.UUID, version_id: uuid.UUID) -> QuestionVersionResponse:
    """
    Publish a version, superseding the one it replaces.

    Args:
        question_id: Question the version must belong to.
        version_id: Version to publish.

    Returns:
        QuestionVersionResponse: The published version.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: No such version on this question, or the caller is not an
            administrator.
        HTTPException 409: The version has already been superseded.
        HTTPException 422: The rubric is incomplete.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/admin/questions versions publish endpoint")
        version = await AdminQuestionController().publish_version(
            question_id=question_id, version_id=version_id
        )
        return QuestionVersionResponse.model_validate(version)
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/admin/questions publish endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/admin/questions publish endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@admin_question_router.get(
    "/questions/{question_id}/versions/{version_id}/validation",
    response_model=RubricValidationResponse,
)
async def validate_version(
    question_id: uuid.UUID, version_id: uuid.UUID
) -> RubricValidationResponse:
    """
    Report whether a version is complete enough to publish, without publishing it.

    Args:
        question_id: Question the version must belong to.
        version_id: Version to check.

    Returns:
        RubricValidationResponse: Validity, blocking errors, and quality warnings.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: No such version on this question, or the caller is not an
            administrator.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/admin/questions versions validation endpoint")
        result = await AdminQuestionController().validate_version(
            question_id=question_id, version_id=version_id
        )
        return RubricValidationResponse(**result)
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/admin/questions validation endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/admin/questions validation endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error
