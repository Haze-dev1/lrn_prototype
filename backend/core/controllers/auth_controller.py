"""Authentication orchestration: registration, sign-in, rotation, and sign-out."""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, Response, status

from commons.rate_limit import check_rate_limit, reset_rate_limit
from commons.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    password_needs_rehash,
    verify_password,
)
from core import logger
from core.config.settings import settings
from core.constants.enums import UserStatus
from core.cruds.auth_crud import CRUDRefreshToken
from core.cruds.user_crud import CRUDProfile, CRUDUser
from core.models.user_model import User
from core.services.analytics.events import AnalyticsEvent
from core.services.analytics.service import track
from core.services.auth.google_service import GoogleIdentityError, GoogleIdentityService

logging = logger(__name__)

# Returned for every failed sign-in regardless of cause. Saying "no such account" or "wrong
# password" would turn the login form into an account-enumeration oracle.
_INVALID_CREDENTIALS = "Incorrect email or password"


class AuthController:
    """Owns the account lifecycle from registration through session rotation."""

    def __init__(self) -> None:
        """Initialise the controller with the CRUD layers and services it coordinates."""
        self.CRUDUser = CRUDUser()
        self.CRUDProfile = CRUDProfile()
        self.CRUDRefreshToken = CRUDRefreshToken()
        self.GoogleIdentityService = GoogleIdentityService()

    # --- Configuration ------------------------------------------------------------------

    def sign_in_config(self) -> dict:
        """
        Report which sign-in methods this deployment offers.

        Lets the interface render the Google button only where the API can actually verify a
        Google token, so a deployment without a client ID shows one working sign-in method
        rather than a button that answers 503 when pressed.

        Returns:
            dict: Whether Google sign-in is enabled, and the public client ID when it is.
        """
        logging.info("Executing AuthController.sign_in_config")
        return {
            "google_enabled": settings.google_enabled,
            # Only ever the client ID. There is no client secret in this application to leak.
            "google_client_id": settings.GOOGLE_CLIENT_ID if settings.google_enabled else None,
        }

    # --- Rate limiting ------------------------------------------------------------------

    async def _enforce_rate_limit(
        self, *, bucket: str, identifier: str, limit: int, window_seconds: int
    ) -> None:
        """
        Reject the request when a rate-limit bucket is exhausted.

        Args:
            bucket: Logical limit name.
            identifier: What is being limited — a client address or an account.
            limit: Maximum requests per window.
            window_seconds: Window length in seconds.

        Raises:
            HTTPException 429: The bucket is exhausted, with a Retry-After header.
        """
        result = await check_rate_limit(
            bucket=bucket, identifier=identifier, limit=limit, window_seconds=window_seconds
        )
        if not result.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please try again later.",
                headers={"Retry-After": str(result.retry_after_seconds)},
            )

    # --- Session cookies ----------------------------------------------------------------

    def _set_session_cookies(
        self, *, response: Response, access_token: str, refresh_token: str
    ) -> None:
        """
        Write the access and refresh tokens as hardened cookies.

        HttpOnly so page scripts cannot read them, SameSite=Lax so another site cannot drive a
        state-changing request with them, and Secure in production. Because the proxy serves the
        API and the web app on one origin, this needs no CORS exemption and no token in
        browser-readable storage.

        Args:
            response: The response to attach cookies to.
            access_token: The signed access token.
            refresh_token: The opaque refresh token.
        """
        secure = settings.cookie_secure
        response.set_cookie(
            settings.ACCESS_COOKIE_NAME,
            access_token,
            max_age=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
            domain=settings.COOKIE_DOMAIN,
        )
        response.set_cookie(
            settings.REFRESH_COOKIE_NAME,
            refresh_token,
            max_age=settings.REFRESH_TOKEN_TTL_DAYS * 86400,
            httponly=True,
            secure=secure,
            samesite="lax",
            path="/",
            domain=settings.COOKIE_DOMAIN,
        )

    def clear_session_cookies(self, *, response: Response) -> None:
        """
        Remove the session cookies from the client.

        Args:
            response: The response to clear cookies on.
        """
        for name in (settings.ACCESS_COOKIE_NAME, settings.REFRESH_COOKIE_NAME):
            response.delete_cookie(
                name,
                path="/",
                domain=settings.COOKIE_DOMAIN,
                httponly=True,
                secure=settings.cookie_secure,
                samesite="lax",
            )

    async def _issue_session(
        self, *, response: Response, user: User, family_id: uuid.UUID | None = None
    ) -> None:
        """
        Mint a token pair for a user and attach it to the response.

        Args:
            response: The response to attach cookies to.
            user: The authenticated user.
            family_id: Rotation family to continue, or None to begin a new one.

        Raises:
            Exception: If storing the refresh token fails.
        """
        access_token, _ = create_access_token(user_id=user.id)
        refresh_token = generate_refresh_token()
        await self.CRUDRefreshToken.create(
            user_id=user.id,
            token_hash=hash_refresh_token(refresh_token),
            family_id=family_id,
        )
        self._set_session_cookies(
            response=response, access_token=access_token, refresh_token=refresh_token
        )

    # --- Registration and sign-in -------------------------------------------------------

    async def register(
        self, *, email: str, password: str, response: Response, client_id: str
    ) -> dict:
        """
        Create an account with an email and password, and sign the user in.

        A duplicate email returns the same generic conflict whether or not the address exists, so
        registration cannot be used to discover who has an account.

        Args:
            email: Email address to register.
            password: Plaintext password, already length-validated by the request schema.
            response: Response to attach session cookies to.
            client_id: Rate-limiting identifier for the caller.

        Returns:
            dict: The created user's public representation.

        Raises:
            HTTPException 409: An account already exists for this email.
            HTTPException 429: Too many registration attempts from this client.
            HTTPException 500: Unexpected failure creating the account.
        """
        try:
            logging.info("Executing AuthController.register")
            await self._enforce_rate_limit(
                bucket="register",
                identifier=client_id,
                limit=settings.REGISTER_RATE_LIMIT_PER_IP,
                window_seconds=settings.REGISTER_RATE_LIMIT_WINDOW_SECONDS,
            )

            normalised = email.strip().lower()
            if await self.CRUDUser.get_by_email(email=normalised) is not None:
                logging.warning("Registration attempted for an address that already exists")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="That email address cannot be used to register.",
                )

            user = await self.CRUDUser.create(
                obj_in={"email": normalised, "password_hash": hash_password(password)}
            )
            await self.CRUDProfile.create(user_id=user.id)
            await self._issue_session(response=response, user=user)

            logging.info(f"Registered new account {user.id}")
            track(
                event=AnalyticsEvent.USER_SIGNED_UP,
                user_id=user.id,
                properties={"source": "password"},
            )
            return await self.build_current_user(user=user)
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AuthController.register: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal Server Error",
            ) from error

    async def login(self, *, email: str, password: str, response: Response, client_id: str) -> dict:
        """
        Authenticate an email and password, and start a session.

        Password verification runs even when no account matches, so the response takes comparable
        time either way and timing cannot reveal which addresses are registered.

        Args:
            email: Submitted email address.
            password: Submitted password.
            response: Response to attach session cookies to.
            client_id: Rate-limiting identifier for the caller.

        Returns:
            dict: The authenticated user's public representation.

        Raises:
            HTTPException 401: The credentials are not valid.
            HTTPException 403: The account exists but is not active.
            HTTPException 429: Too many sign-in attempts.
            HTTPException 500: Unexpected failure during sign-in.
        """
        try:
            logging.info("Executing AuthController.login")
            normalised = email.strip().lower()
            # The per-account bucket is checked first and is the one that actually stops password
            # guessing; the per-IP bucket only catches crude floods.
            await self._enforce_rate_limit(
                bucket="login_account",
                identifier=normalised,
                limit=settings.LOGIN_RATE_LIMIT_PER_ACCOUNT,
                window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
            )
            await self._enforce_rate_limit(
                bucket="login_ip",
                identifier=client_id,
                limit=settings.LOGIN_RATE_LIMIT_PER_IP,
                window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
            )
            user = await self.CRUDUser.get_by_email(email=normalised)
            if not verify_password(
                password=password, password_hash=user.password_hash if user else None
            ):
                logging.warning("Failed sign-in attempt")
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS
                )

            assert user is not None  # noqa: S101 — verify_password returns False without a user
            if user.status != UserStatus.ACTIVE:
                logging.warning(f"Sign-in blocked for non-active user {user.id}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="This account is not active"
                )

            # Transparently upgrade a hash made with weaker parameters, now that the plaintext is
            # available and already verified.
            if user.password_hash and password_needs_rehash(user.password_hash):
                logging.info(f"Upgrading password hash parameters for user {user.id}")
                await self.CRUDUser.update(
                    user_id=user.id, obj_in={"password_hash": hash_password(password)}
                )

            await self._issue_session(response=response, user=user)
            await self.CRUDUser.record_login(user_id=user.id)
            # A user who mistyped a few times then succeeded should not stay penalised.
            await reset_rate_limit(bucket="login_account", identifier=normalised)
            await reset_rate_limit(bucket="login_ip", identifier=client_id)

            logging.info(f"User {user.id} signed in")
            return await self.build_current_user(user=user)
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AuthController.login: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal Server Error",
            ) from error

    async def google_sign_in(self, *, id_token: str, response: Response) -> dict:
        """
        Sign in or register using a verified Google ID token.

        An existing password account with the same verified address is linked rather than
        duplicated, so a student who registered with a password and later uses Google reaches the
        same account and the same evidence.

        Args:
            id_token: The ID token issued by Google to the browser.
            response: Response to attach session cookies to.

        Returns:
            dict: The authenticated user's public representation.

        Raises:
            HTTPException 401: The token could not be verified.
            HTTPException 403: The matched account is not active.
            HTTPException 503: Google sign-in is not configured.
            HTTPException 500: Unexpected failure during sign-in.
        """
        try:
            logging.info("Executing AuthController.google_sign_in")
            if not settings.google_enabled:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Google sign-in is not available",
                )

            try:
                identity = await self.GoogleIdentityService.verify_id_token(id_token=id_token)
            except GoogleIdentityError as error:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)
                ) from error

            user = await self.CRUDUser.get_by_google_sub(google_sub=identity["sub"])
            if user is None:
                existing = await self.CRUDUser.get_by_email(email=identity["email"])
                if existing is not None:
                    # Linking is only safe because the service rejects unverified Google emails;
                    # otherwise this would let anyone claim an account by asserting its address.
                    logging.info(f"Linking Google identity to existing account {existing.id}")
                    user = await self.CRUDUser.update(
                        user_id=existing.id,
                        obj_in={
                            "google_sub": identity["sub"],
                            "email_verified_at": existing.email_verified_at or datetime.now(UTC),
                        },
                    )
                else:
                    user = await self.CRUDUser.create(
                        obj_in={
                            "email": identity["email"],
                            "google_sub": identity["sub"],
                            "email_verified_at": datetime.now(UTC),
                        }
                    )
                    await self.CRUDProfile.create(user_id=user.id)
                    logging.info(f"Registered new account {user.id} via Google")
                    track(
                        event=AnalyticsEvent.USER_SIGNED_UP,
                        user_id=user.id,
                        properties={"source": "google"},
                    )

            assert user is not None  # noqa: S101 — every branch above assigns a user
            if user.status != UserStatus.ACTIVE:
                logging.warning(f"Google sign-in blocked for non-active user {user.id}")
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="This account is not active"
                )

            await self._issue_session(response=response, user=user)
            await self.CRUDUser.record_login(user_id=user.id)
            return await self.build_current_user(user=user)
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AuthController.google_sign_in: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal Server Error",
            ) from error

    # --- Rotation and sign-out ----------------------------------------------------------

    async def refresh(self, *, refresh_token: str | None, response: Response) -> dict:
        """
        Rotate a refresh token and issue a new session.

        Presenting a token that was already rotated means the original was captured, since a
        legitimate client discards each token as it uses it. That revokes the whole rotation
        family: revoking only the reused token would leave the attacker and the real user
        alternating rotations indefinitely.

        Args:
            refresh_token: The refresh token from the request cookie.
            response: Response to attach the new session cookies to.

        Returns:
            dict: The user's public representation.

        Raises:
            HTTPException 401: The token is missing, unknown, expired, or already used.
            HTTPException 403: The account is no longer active.
            HTTPException 500: Unexpected failure during rotation.
        """
        try:
            logging.info("Executing AuthController.refresh")
            if not refresh_token:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
                )

            record = await self.CRUDRefreshToken.get_by_hash(
                token_hash=hash_refresh_token(refresh_token)
            )
            if record is None:
                logging.warning("Refresh presented with an unrecognised token")
                self.clear_session_cookies(response=response)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
                )

            if record.revoked_at is not None:
                logging.warning(
                    f"Refresh token reuse detected for user {record.user_id}; "
                    f"revoking family {record.family_id}"
                )
                await self.CRUDRefreshToken.revoke_family(family_id=record.family_id)
                self.clear_session_cookies(response=response)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
                )

            if record.expires_at <= datetime.now(UTC):
                logging.warning(f"Refresh token expired for user {record.user_id}")
                await self.CRUDRefreshToken.revoke(token_id=record.id)
                self.clear_session_cookies(response=response)
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
                )

            user = await self.CRUDUser.get_by_id(user_id=record.user_id)
            if user is None or user.status != UserStatus.ACTIVE:
                logging.warning(f"Refresh blocked for unavailable user {record.user_id}")
                await self.CRUDRefreshToken.revoke_family(family_id=record.family_id)
                self.clear_session_cookies(response=response)
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="This account is not active"
                )

            await self.CRUDRefreshToken.revoke(token_id=record.id)
            await self._issue_session(response=response, user=user, family_id=record.family_id)
            return await self.build_current_user(user=user)
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AuthController.refresh: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal Server Error",
            ) from error

    async def logout(self, *, refresh_token: str | None, response: Response) -> dict:
        """
        End the current session.

        Revokes the presented token's whole family, so the rotation chain started by this login
        cannot be continued. Always reports success: whether the token was already invalid is not
        information a caller needs, and signing out should never appear to fail.

        Args:
            refresh_token: The refresh token from the request cookie, if present.
            response: Response to clear session cookies on.

        Returns:
            dict: An acknowledgement message.
        """
        logging.info("Executing AuthController.logout")
        try:
            if refresh_token:
                record = await self.CRUDRefreshToken.get_by_hash(
                    token_hash=hash_refresh_token(refresh_token)
                )
                if record is not None:
                    await self.CRUDRefreshToken.revoke_family(family_id=record.family_id)
        except Exception as error:
            logging.error(f"Error in AuthController.logout: {error}")

        self.clear_session_cookies(response=response)
        return {"message": "Signed out"}

    async def logout_everywhere(self, *, user: User, response: Response) -> dict:
        """
        Revoke every session belonging to the user.

        Args:
            user: The authenticated user.
            response: Response to clear session cookies on.

        Returns:
            dict: An acknowledgement message.

        Raises:
            HTTPException 500: Unexpected failure revoking sessions.
        """
        try:
            logging.info("Executing AuthController.logout_everywhere")
            revoked = await self.CRUDRefreshToken.revoke_all_for_user(user_id=user.id)
            self.clear_session_cookies(response=response)
            logging.info(f"Revoked {revoked} sessions for user {user.id}")
            return {"message": "Signed out on all devices"}
        except Exception as error:
            logging.error(f"Error in AuthController.logout_everywhere: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal Server Error",
            ) from error

    # --- Shared representation ----------------------------------------------------------

    async def build_current_user(self, *, user: User) -> dict:
        """
        Assemble the client-facing representation of a signed-in user.

        Args:
            user: The authenticated user.

        Returns:
            dict: Public account fields and the profile, if one exists.

        Raises:
            Exception: If reading the profile fails.
        """
        profile = await self.CRUDProfile.get_by_user_id(user_id=user.id)
        return {
            "id": user.id,
            "email": user.email,
            "is_admin": user.is_admin,
            "email_verified": user.email_verified_at is not None,
            "onboarding_complete": bool(profile and profile.onboarding_completed_at),
            "profile": profile,
        }
