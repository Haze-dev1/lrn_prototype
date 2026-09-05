"""Authentication endpoints.

Routes stay thin: they parse the request, read cookies, delegate to the controller, and translate
failures. Session cookies are written by the controller because it owns their lifetime.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from commons.auth import client_identifier, get_current_user
from core import logger
from core.apis.schemas.requests.auth_request import (
    GoogleSignInRequest,
    LoginRequest,
    RegisterRequest,
)
from core.apis.schemas.responses.auth_response import (
    AuthConfigResponse,
    CurrentUserResponse,
    MessageResponse,
)
from core.config.settings import settings
from core.controllers.auth_controller import AuthController
from core.models.user_model import User

auth_router = APIRouter()
logging = logger(__name__)


@auth_router.get("/v1/auth/config", response_model=AuthConfigResponse)
async def sign_in_config() -> AuthConfigResponse:
    """
    Report which sign-in methods this deployment offers.

    Public and unauthenticated, because it is read by the sign-in and sign-up pages before anyone
    has a session. It returns configuration, never a credential: the Google client ID is public
    by design and no client secret exists in this application.

    Returns:
        AuthConfigResponse: Whether Google sign-in is enabled, and the client ID when it is.

    Raises:
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/auth/config endpoint")
        return AuthConfigResponse(**AuthController().sign_in_config())
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/auth/config endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/auth/config endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@auth_router.post(
    "/v1/auth/register",
    status_code=status.HTTP_201_CREATED,
    response_model=CurrentUserResponse,
)
async def register(
    request: RegisterRequest, http_request: Request, response: Response
) -> CurrentUserResponse:
    """
    Create an account with an email address and password.

    Signs the new user in immediately and sets session cookies, so registration does not
    dead-end on a sign-in form.

    Args:
        request: Registration payload.
        http_request: Incoming request, used to derive a rate-limit identifier.
        response: Response the session cookies are attached to.

    Returns:
        CurrentUserResponse: The newly created user.

    Raises:
        HTTPException 409: An account already exists for this email.
        HTTPException 429: Too many registration attempts.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/auth/register endpoint")
        result = await AuthController().register(
            email=request.email,
            password=request.password,
            response=response,
            client_id=client_identifier(http_request),
        )
        return CurrentUserResponse(**result)
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/auth/register endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/auth/register endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@auth_router.post("/v1/auth/login", response_model=CurrentUserResponse)
async def login(
    request: LoginRequest, http_request: Request, response: Response
) -> CurrentUserResponse:
    """
    Sign in with an email address and password.

    Args:
        request: Sign-in payload.
        http_request: Incoming request, used to derive a rate-limit identifier.
        response: Response the session cookies are attached to.

    Returns:
        CurrentUserResponse: The authenticated user.

    Raises:
        HTTPException 401: Incorrect credentials.
        HTTPException 403: The account is not active.
        HTTPException 429: Too many sign-in attempts.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/auth/login endpoint")
        result = await AuthController().login(
            email=request.email,
            password=request.password,
            response=response,
            client_id=client_identifier(http_request),
        )
        return CurrentUserResponse(**result)
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/auth/login endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/auth/login endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@auth_router.post("/v1/auth/google", response_model=CurrentUserResponse)
async def google_sign_in(request: GoogleSignInRequest, response: Response) -> CurrentUserResponse:
    """
    Sign in or register using a Google ID token.

    The token is verified server-side against Google's published keys; the client cannot assert
    an identity by itself.

    Args:
        request: Payload carrying the Google ID token.
        response: Response the session cookies are attached to.

    Returns:
        CurrentUserResponse: The authenticated user.

    Raises:
        HTTPException 401: The Google token could not be verified.
        HTTPException 403: The account is not active.
        HTTPException 503: Google sign-in is not configured.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/auth/google endpoint")
        result = await AuthController().google_sign_in(id_token=request.id_token, response=response)
        return CurrentUserResponse(**result)
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/auth/google endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/auth/google endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@auth_router.post("/v1/auth/refresh", response_model=CurrentUserResponse)
async def refresh(http_request: Request, response: Response) -> CurrentUserResponse:
    """
    Rotate the refresh token and issue a new session.

    Reads the refresh token from its HttpOnly cookie rather than the body, so page scripts can
    neither read nor replay it.

    Args:
        http_request: Incoming request carrying the refresh cookie.
        response: Response the new session cookies are attached to.

    Returns:
        CurrentUserResponse: The authenticated user.

    Raises:
        HTTPException 401: Missing, unknown, expired, or already-used refresh token.
        HTTPException 403: The account is no longer active.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/auth/refresh endpoint")
        result = await AuthController().refresh(
            refresh_token=http_request.cookies.get(settings.REFRESH_COOKIE_NAME),
            response=response,
        )
        return CurrentUserResponse(**result)
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/auth/refresh endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/auth/refresh endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@auth_router.post("/v1/auth/logout", response_model=MessageResponse)
async def logout(http_request: Request, response: Response) -> MessageResponse:
    """
    End the current session.

    Requires no authentication and always succeeds: signing out must work even when the session
    has already expired, and a failed sign-out would leave the user believing they are still in.

    Args:
        http_request: Incoming request carrying the refresh cookie, if any.
        response: Response the session cookies are cleared on.

    Returns:
        MessageResponse: Acknowledgement.
    """
    logging.info("Calling POST /v1/auth/logout endpoint")
    result = await AuthController().logout(
        refresh_token=http_request.cookies.get(settings.REFRESH_COOKIE_NAME), response=response
    )
    return MessageResponse(**result)


@auth_router.post("/v1/auth/logout-all", response_model=MessageResponse)
async def logout_everywhere(
    response: Response, user: User = Depends(get_current_user)
) -> MessageResponse:
    """
    Revoke every session belonging to the authenticated user.

    Args:
        response: Response the session cookies are cleared on.
        user: The authenticated user.

    Returns:
        MessageResponse: Acknowledgement.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/auth/logout-all endpoint")
        result = await AuthController().logout_everywhere(user=user, response=response)
        return MessageResponse(**result)
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/auth/logout-all endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/auth/logout-all endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@auth_router.get("/v1/auth/me", response_model=CurrentUserResponse)
async def current_user(user: User = Depends(get_current_user)) -> CurrentUserResponse:
    """
    Return the signed-in user and their profile.

    Args:
        user: The authenticated user.

    Returns:
        CurrentUserResponse: The authenticated user.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 403: The account is not active.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/auth/me endpoint")
        result = await AuthController().build_current_user(user=user)
        return CurrentUserResponse(**result)
    except HTTPException as httperror:
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/auth/me endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error
