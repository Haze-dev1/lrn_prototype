"""Profile, onboarding, consent, and account data control endpoints.

Every route here operates on the authenticated caller's own record. None of them accept a user ID
from the client, which removes the whole class of "change the ID in the URL" authorisation bugs.
"""

from fastapi import APIRouter, Depends, HTTPException, Response, status

from commons.auth import get_current_user
from core import logger
from core.apis.schemas.requests.auth_request import (
    AccountDeletionRequest,
    ConsentUpdateRequest,
    OnboardingRequest,
    ProfileUpdateRequest,
)
from core.apis.schemas.responses.auth_response import (
    CurrentUserResponse,
    DataExportResponse,
    MessageResponse,
)
from core.controllers.account_controller import AccountController
from core.controllers.auth_controller import AuthController
from core.models.user_model import User

account_router = APIRouter()
logging = logger(__name__)


@account_router.post("/v1/onboarding", response_model=CurrentUserResponse)
async def complete_onboarding(
    request: OnboardingRequest, user: User = Depends(get_current_user)
) -> CurrentUserResponse:
    """
    Save onboarding answers for the authenticated user.

    Args:
        request: School, graduation year and target role.
        user: The authenticated user.

    Returns:
        CurrentUserResponse: The user with their updated profile.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: The user has no profile record.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/onboarding endpoint")
        await AccountController().complete_onboarding(user=user, payload=request.model_dump())
        return CurrentUserResponse(**await AuthController().build_current_user(user=user))
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/onboarding endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/onboarding endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@account_router.patch("/v1/profile", response_model=CurrentUserResponse)
async def update_profile(
    request: ProfileUpdateRequest, user: User = Depends(get_current_user)
) -> CurrentUserResponse:
    """
    Update the authenticated user's editable profile fields.

    Args:
        request: Partial profile payload.
        user: The authenticated user.

    Returns:
        CurrentUserResponse: The user with their updated profile.

    Raises:
        HTTPException 400: No editable fields were supplied.
        HTTPException 401: Not authenticated.
        HTTPException 404: The user has no profile record.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling PATCH /v1/profile endpoint")
        await AccountController().update_profile(
            user=user, payload=request.model_dump(exclude_unset=True)
        )
        return CurrentUserResponse(**await AuthController().build_current_user(user=user))
    except HTTPException as httperror:
        logging.error(f"Error in PATCH /v1/profile endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in PATCH /v1/profile endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@account_router.put("/v1/account/recruiting-consent", response_model=CurrentUserResponse)
async def set_recruiting_consent(
    request: ConsentUpdateRequest, user: User = Depends(get_current_user)
) -> CurrentUserResponse:
    """
    Grant or withdraw recruiting consent.

    A dedicated endpoint so consent can never be changed as a side effect of saving something
    else, and so withdrawing it is exactly as easy as granting it.

    Args:
        request: The desired consent state.
        user: The authenticated user.

    Returns:
        CurrentUserResponse: The user with their updated profile.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: The user has no profile record.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling PUT /v1/account/recruiting-consent endpoint")
        await AccountController().set_recruiting_consent(
            user=user, granted=request.recruiting_consent
        )
        return CurrentUserResponse(**await AuthController().build_current_user(user=user))
    except HTTPException as httperror:
        logging.error(f"Error in PUT /v1/account/recruiting-consent endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in PUT /v1/account/recruiting-consent endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@account_router.get("/v1/account/export", response_model=DataExportResponse)
async def export_data(user: User = Depends(get_current_user)) -> DataExportResponse:
    """
    Export everything the authenticated user's account holds.

    Returns their own answers and grades, but never ideal answers, rubrics or raw model
    responses — an export must not become a way around question protection.

    Args:
        user: The authenticated user.

    Returns:
        DataExportResponse: The user's exportable data.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/account/export endpoint")
        return DataExportResponse(**await AccountController().export_data(user=user))
    except HTTPException as httperror:
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/account/export endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@account_router.post("/v1/account/delete", response_model=MessageResponse)
async def delete_account(
    request: AccountDeletionRequest, response: Response, user: User = Depends(get_current_user)
) -> MessageResponse:
    """
    Permanently delete the authenticated user's account and all associated data.

    POST rather than DELETE because it carries a confirmation body; irreversible, and the session
    cookies are cleared so the client cannot continue with tokens for an account that is gone.

    Args:
        request: Confirmation phrase and, for password accounts, the current password.
        response: Response the session cookies are cleared on.
        user: The authenticated user.

    Returns:
        MessageResponse: Acknowledgement.

    Raises:
        HTTPException 400: Missing confirmation or password.
        HTTPException 401: Not authenticated, or the password is incorrect.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/account/delete endpoint")
        result = await AccountController().delete_account(user=user, password=request.password)
        AuthController().clear_session_cookies(response=response)
        return MessageResponse(**result)
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/account/delete endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/account/delete endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error
