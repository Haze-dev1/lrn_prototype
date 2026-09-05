"""Tests for authentication, session rotation, and authorization.

Exercised over HTTP through the ASGI transport rather than against controllers directly, because
what matters here is what an attacker can reach: the cookie attributes, the status codes, and the
response bodies as actually returned.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from commons.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from core.config.settings import settings
from core.constants.enums import UserStatus
from core.cruds.auth_crud import CRUDRefreshToken
from core.cruds.user_crud import CRUDProfile, CRUDUser
from tests.conftest import requires_database
from tests.factories import make_user

PASSWORD = "correct-horse-battery-staple"


async def register(client: AsyncClient, email: str, password: str = PASSWORD):
    """
    Register an account through the API.

    Args:
        client: HTTP client bound to the application.
        email: Email address to register.
        password: Password to register with.

    Returns:
        Response: The registration response.
    """
    return await client.post("/v1/auth/register", json={"email": email, "password": password})


def unique_email(prefix: str = "student") -> str:
    """
    Build an email address unique to one test.

    Args:
        prefix: Readable prefix for the local part.

    Returns:
        str: A unique email address.
    """
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.edu"


class TestPasswordHashing:
    """The password primitives, tested without a database."""

    def test_a_hash_does_not_contain_the_password(self) -> None:
        """The stored value reveals nothing about the plaintext."""
        digest = hash_password(PASSWORD)

        assert PASSWORD not in digest
        assert digest.startswith("$argon2id$")

    def test_the_same_password_hashes_differently_each_time(self) -> None:
        """Per-hash salting means identical passwords are not identifiable in the database."""
        assert hash_password(PASSWORD) != hash_password(PASSWORD)

    def test_the_correct_password_verifies(self) -> None:
        """A matching password is accepted."""
        assert verify_password(password=PASSWORD, password_hash=hash_password(PASSWORD)) is True

    def test_a_wrong_password_is_rejected(self) -> None:
        """A non-matching password is refused."""
        assert verify_password(password="wrong", password_hash=hash_password(PASSWORD)) is False

    def test_verification_against_no_hash_is_refused(self) -> None:
        """A Google-only account cannot be signed into with any password."""
        assert verify_password(password=PASSWORD, password_hash=None) is False

    def test_a_corrupt_hash_is_refused_rather_than_raising(self) -> None:
        """Malformed stored data fails closed instead of erroring out of the login path."""
        assert verify_password(password=PASSWORD, password_hash="not-a-valid-hash") is False


class TestAccessTokens:
    """Access token signing and verification."""

    def test_a_token_round_trips_to_its_subject(self) -> None:
        """A freshly minted token identifies the user it was issued for."""
        user_id = uuid.uuid4()
        token, _ = create_access_token(user_id=user_id)

        assert decode_access_token(token) == user_id

    def test_a_tampered_token_is_rejected(self) -> None:
        """Altering the payload invalidates the signature."""
        token, _ = create_access_token(user_id=uuid.uuid4())
        header, payload, signature = token.split(".")
        tampered = f"{header}.{payload[:-4]}AAAA.{signature}"

        assert decode_access_token(tampered) is None

    def test_an_unsigned_token_is_rejected(self) -> None:
        """A token claiming 'alg: none' must not be accepted."""
        import base64
        import json

        def b64(data: dict) -> str:
            raw = json.dumps(data).encode()
            return base64.urlsafe_b64encode(raw).decode().rstrip("=")

        forged = (
            f"{b64({'alg': 'none', 'typ': 'JWT'})}."
            f"{b64({'sub': str(uuid.uuid4()), 'typ': 'access', 'exp': 9999999999, 'iat': 1})}."
        )

        assert decode_access_token(forged) is None

    def test_a_token_signed_with_another_key_is_rejected(self) -> None:
        """A token minted with a different secret does not verify."""
        import jwt

        forged = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "typ": "access",
                "iat": int(datetime.now(UTC).timestamp()),
                "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            },
            "a-completely-different-secret-value-here",
            algorithm="HS256",
        )

        assert decode_access_token(forged) is None

    def test_an_expired_token_is_rejected(self) -> None:
        """Expiry is enforced."""
        import jwt

        expired = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "typ": "access",
                "iat": int((datetime.now(UTC) - timedelta(hours=2)).timestamp()),
                "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )

        assert decode_access_token(expired) is None

    def test_a_token_of_the_wrong_type_is_rejected(self) -> None:
        """A refresh-typed token cannot be presented as an access token."""
        import jwt

        wrong_type = jwt.encode(
            {
                "sub": str(uuid.uuid4()),
                "typ": "refresh",
                "iat": int(datetime.now(UTC).timestamp()),
                "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
            },
            settings.JWT_SECRET,
            algorithm=settings.JWT_ALGORITHM,
        )

        assert decode_access_token(wrong_type) is None

    def test_a_token_carries_no_authorization_claims(self) -> None:
        """Admin rights are read from the database, never from the token."""
        import jwt

        token, _ = create_access_token(user_id=uuid.uuid4())
        claims = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])

        assert set(claims) == {"sub", "typ", "iat", "exp", "jti"}


@requires_database
@pytest.mark.usefixtures("migrated_database")
class TestRegistration:
    """Account creation over HTTP."""

    async def test_registration_creates_an_account_and_signs_in(self, client: AsyncClient) -> None:
        """A new account is usable immediately, without a separate sign-in step."""
        response = await register(client, unique_email())

        assert response.status_code == 201
        assert settings.ACCESS_COOKIE_NAME in response.cookies
        assert settings.REFRESH_COOKIE_NAME in response.cookies

    async def test_session_cookies_are_hardened(self, client: AsyncClient) -> None:
        """Session cookies are HttpOnly and SameSite=Lax, so scripts and other sites cannot use them."""
        response = await register(client, unique_email())

        cookie_headers = [
            value for key, value in response.headers.multi_items() if key.lower() == "set-cookie"
        ]
        assert len(cookie_headers) == 2
        for header in cookie_headers:
            assert "HttpOnly" in header
            assert "SameSite=lax" in header.lower().replace("samesite=lax", "SameSite=lax")

    async def test_a_new_account_has_consent_off_and_onboarding_incomplete(
        self, client: AsyncClient
    ) -> None:
        """Signing up grants no recruiting consent and completes no onboarding."""
        response = await register(client, unique_email())
        body = response.json()

        assert body["onboarding_complete"] is False
        assert body["profile"]["recruiting_consent"] is False

    async def test_the_response_never_includes_credential_fields(self, client: AsyncClient) -> None:
        """No password hash or Google subject can reach the client."""
        body = (await register(client, unique_email())).json()

        assert "password_hash" not in body
        assert "google_sub" not in body

    async def test_email_is_normalised_to_lowercase(self, client: AsyncClient) -> None:
        """Casing does not create a second account."""
        email = unique_email()
        response = await register(client, email.upper())

        assert response.json()["email"] == email.lower()

    async def test_a_duplicate_registration_is_refused_without_confirming_the_address(
        self, client: AsyncClient
    ) -> None:
        """The conflict message must not confirm that the address is registered."""
        email = unique_email()
        await register(client, email)

        response = await register(client, email.upper())

        assert response.status_code == 409
        assert "already" not in response.json()["detail"].lower()

    @pytest.mark.parametrize(
        "payload",
        [
            {"email": "not-an-email", "password": PASSWORD},
            {"email": "a@b.edu", "password": "short"},
            {"email": "a@b.edu", "password": "            "},
        ],
    )
    async def test_invalid_payloads_are_rejected(self, client: AsyncClient, payload: dict) -> None:
        """Malformed credentials never reach the database."""
        response = await client.post("/v1/auth/register", json=payload)

        assert response.status_code == 422


@requires_database
@pytest.mark.usefixtures("migrated_database")
class TestLogin:
    """Sign-in behaviour, including what it refuses to disclose."""

    async def test_correct_credentials_sign_in(self, client: AsyncClient) -> None:
        """A valid email and password start a session."""
        email = unique_email()
        await register(client, email)

        response = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})

        assert response.status_code == 200
        assert response.json()["email"] == email

    async def test_a_wrong_password_is_refused(self, client: AsyncClient) -> None:
        """An incorrect password does not sign in."""
        email = unique_email()
        await register(client, email)

        response = await client.post(
            "/v1/auth/login", json={"email": email, "password": "not-the-password"}
        )

        assert response.status_code == 401

    async def test_unknown_and_known_accounts_fail_identically(self, client: AsyncClient) -> None:
        """The login form must not become an account-enumeration oracle."""
        email = unique_email()
        await register(client, email)

        known = await client.post(
            "/v1/auth/login", json={"email": email, "password": "not-the-password"}
        )
        unknown = await client.post(
            "/v1/auth/login", json={"email": unique_email(), "password": "not-the-password"}
        )

        assert known.status_code == unknown.status_code == 401
        assert known.json() == unknown.json()

    async def test_a_suspended_account_cannot_sign_in(self, client: AsyncClient) -> None:
        """Suspension blocks sign-in with a distinct status from bad credentials."""
        email = unique_email()
        await register(client, email)
        user = await CRUDUser().get_by_email(email=email)
        assert user is not None
        await CRUDUser().update(user_id=user.id, obj_in={"status": UserStatus.SUSPENDED})

        response = await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})

        assert response.status_code == 403

    async def test_a_google_only_account_cannot_be_signed_into_with_a_password(
        self, client: AsyncClient
    ) -> None:
        """An account with no password cannot be accessed by guessing one."""
        user = await CRUDUser().create(
            obj_in={
                "email": unique_email("google"),
                "google_sub": f"sub-{uuid.uuid4().hex}",
                "password_hash": None,
            }
        )
        await CRUDProfile().create(user_id=user.id)

        response = await client.post(
            "/v1/auth/login", json={"email": user.email, "password": PASSWORD}
        )

        assert response.status_code == 401


@requires_database
@pytest.mark.usefixtures("migrated_database")
class TestSessionVerification:
    """What the protected endpoints accept as proof of identity."""

    async def test_a_valid_session_resolves_the_user(self, client: AsyncClient) -> None:
        """A signed-in client can read its own identity."""
        email = unique_email()
        await register(client, email)

        response = await client.get("/v1/auth/me")

        assert response.status_code == 200
        assert response.json()["email"] == email

    async def test_no_cookie_is_unauthenticated(self, client: AsyncClient) -> None:
        """A request without a session is refused."""
        assert (await client.get("/v1/auth/me")).status_code == 401

    async def test_a_forged_cookie_is_refused(self, client: AsyncClient) -> None:
        """A made-up token does not authenticate."""
        client.cookies.set(settings.ACCESS_COOKIE_NAME, "not.a.real.token")

        assert (await client.get("/v1/auth/me")).status_code == 401

    async def test_suspension_takes_effect_without_waiting_for_token_expiry(
        self, client: AsyncClient
    ) -> None:
        """Because the user is loaded per request, suspension applies to existing sessions at once."""
        email = unique_email()
        await register(client, email)
        user = await CRUDUser().get_by_email(email=email)
        assert user is not None

        await CRUDUser().update(user_id=user.id, obj_in={"status": UserStatus.SUSPENDED})

        response = await client.get("/v1/auth/me")
        assert response.status_code == 403

    async def test_a_token_for_a_deleted_user_is_refused(self, client: AsyncClient) -> None:
        """A still-valid token whose subject no longer exists does not authenticate."""
        token, _ = create_access_token(user_id=uuid.uuid4())
        client.cookies.set(settings.ACCESS_COOKIE_NAME, token)

        assert (await client.get("/v1/auth/me")).status_code == 401


@requires_database
@pytest.mark.usefixtures("migrated_database")
class TestRefreshRotation:
    """Refresh tokens rotate, and reuse is treated as theft."""

    async def test_refreshing_issues_a_different_token(self, client: AsyncClient) -> None:
        """Each refresh replaces the token, so a captured one has a short useful life."""
        await register(client, unique_email())
        original = client.cookies[settings.REFRESH_COOKIE_NAME]

        response = await client.post("/v1/auth/refresh")

        assert response.status_code == 200
        assert client.cookies[settings.REFRESH_COOKIE_NAME] != original

    async def test_reusing_a_rotated_token_is_refused(self, client: AsyncClient) -> None:
        """A token that has already been exchanged cannot be used again."""
        await register(client, unique_email())
        original = client.cookies[settings.REFRESH_COOKIE_NAME]
        await client.post("/v1/auth/refresh")

        client.cookies.set(settings.REFRESH_COOKIE_NAME, original)
        response = await client.post("/v1/auth/refresh")

        assert response.status_code == 401

    async def test_reuse_revokes_the_whole_family_including_the_thief_and_the_victim(
        self, client: AsyncClient
    ) -> None:
        """
        Detecting reuse invalidates every token in the chain.

        Revoking only the replayed token would leave the attacker and the legitimate user
        alternating rotations forever, each refreshing after the other.
        """
        await register(client, unique_email())
        stolen = client.cookies[settings.REFRESH_COOKIE_NAME]
        await client.post("/v1/auth/refresh")
        current = client.cookies[settings.REFRESH_COOKIE_NAME]

        client.cookies.set(settings.REFRESH_COOKIE_NAME, stolen)
        await client.post("/v1/auth/refresh")

        client.cookies.set(settings.REFRESH_COOKIE_NAME, current)
        response = await client.post("/v1/auth/refresh")
        assert response.status_code == 401

    async def test_an_unknown_refresh_token_is_refused(self, client: AsyncClient) -> None:
        """A fabricated refresh token does not produce a session."""
        client.cookies.set(settings.REFRESH_COOKIE_NAME, "made-up-token-value")

        assert (await client.post("/v1/auth/refresh")).status_code == 401

    async def test_an_expired_refresh_token_is_refused(self, client: AsyncClient) -> None:
        """Expiry is enforced on the stored record, not only by the cookie's max-age."""
        user = await make_user()
        raw = "expired-token-value-for-test"
        record = await CRUDRefreshToken().create(
            user_id=user.id, token_hash=hash_refresh_token(raw)
        )
        from sqlalchemy import update

        from core.database.database import session
        from core.models.auth_model import RefreshToken

        async with session() as db:
            await db.execute(
                update(RefreshToken)
                .where(RefreshToken.id == record.id)
                .values(expires_at=datetime.now(UTC) - timedelta(days=1))
            )

        client.cookies.set(settings.REFRESH_COOKIE_NAME, raw)
        assert (await client.post("/v1/auth/refresh")).status_code == 401

    async def test_refresh_is_refused_for_a_suspended_account(self, client: AsyncClient) -> None:
        """A suspended user cannot extend their session."""
        email = unique_email()
        await register(client, email)
        user = await CRUDUser().get_by_email(email=email)
        assert user is not None
        await CRUDUser().update(user_id=user.id, obj_in={"status": UserStatus.SUSPENDED})

        assert (await client.post("/v1/auth/refresh")).status_code == 403


@requires_database
@pytest.mark.usefixtures("migrated_database")
class TestSignOut:
    """Ending sessions."""

    async def test_logout_revokes_the_session(self, client: AsyncClient) -> None:
        """After signing out, the refresh token no longer works."""
        await register(client, unique_email())
        token = client.cookies[settings.REFRESH_COOKIE_NAME]

        await client.post("/v1/auth/logout")

        client.cookies.set(settings.REFRESH_COOKIE_NAME, token)
        assert (await client.post("/v1/auth/refresh")).status_code == 401

    async def test_logout_succeeds_without_a_session(self, client: AsyncClient) -> None:
        """Signing out must never appear to fail, even when already signed out."""
        assert (await client.post("/v1/auth/logout")).status_code == 200

    async def test_logout_everywhere_revokes_other_sessions(self, client: AsyncClient) -> None:
        """Sign-out-everywhere invalidates sessions started on other devices."""
        email = unique_email()
        await register(client, email)
        other_device = client.cookies[settings.REFRESH_COOKIE_NAME]

        await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
        await client.post("/v1/auth/logout-all")

        client.cookies.set(settings.REFRESH_COOKIE_NAME, other_device)
        assert (await client.post("/v1/auth/refresh")).status_code == 401

    async def test_logout_everywhere_requires_authentication(self, client: AsyncClient) -> None:
        """An anonymous caller cannot revoke anyone's sessions."""
        assert (await client.post("/v1/auth/logout-all")).status_code == 401


class TestCookieHardening:
    """Cookie attributes are environment-dependent and must not be wrong in production."""

    def test_secure_is_on_in_production(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Session cookies must be HTTPS-only in production."""
        monkeypatch.setattr(settings, "ENVIRONMENT", "production")
        monkeypatch.setattr(settings, "COOKIE_SECURE", None)

        assert settings.cookie_secure is True

    def test_secure_is_off_in_development(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """
        Secure is off locally by design.

        A Secure cookie is silently dropped by the browser on an http:// origin, which presents as
        a login that appears to succeed and then immediately signs the user out.
        """
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        monkeypatch.setattr(settings, "COOKIE_SECURE", None)

        assert settings.cookie_secure is False

    def test_an_explicit_setting_overrides_the_environment_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A deployment behind TLS in staging can force Secure on."""
        monkeypatch.setattr(settings, "ENVIRONMENT", "development")
        monkeypatch.setattr(settings, "COOKIE_SECURE", True)

        assert settings.cookie_secure is True

    def test_google_is_reported_unavailable_without_a_client_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The API can say 'not configured' rather than failing inside token verification."""
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", None)

        assert settings.google_enabled is False


class TestSignInConfig:
    """GET /v1/auth/config — what the sign-in pages read before anyone has a session."""

    async def test_google_is_off_and_carries_no_client_id_when_unconfigured(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fresh clone must render one working sign-in method, not a button that 503s."""
        monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", None)

        response = await client.get("/v1/auth/config")

        assert response.status_code == 200
        assert response.json() == {"google_enabled": False, "google_client_id": None}

    async def test_google_is_on_and_carries_the_client_id_when_configured(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The browser needs the client ID, and it is public by design."""
        monkeypatch.setattr(
            settings, "GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com"
        )

        response = await client.get("/v1/auth/config")

        assert response.status_code == 200
        body = response.json()
        assert body["google_enabled"] is True
        assert body["google_client_id"] == "test-client-id.apps.googleusercontent.com"

    async def test_the_response_carries_nothing_but_the_two_public_fields(
        self, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shape is the enforcement point: no secret can leak from a field that is not there.

        Named explicitly rather than checked loosely, so adding a field to this endpoint has to be
        a deliberate decision rather than something a schema change does silently.
        """
        monkeypatch.setattr(
            settings, "GOOGLE_CLIENT_ID", "test-client-id.apps.googleusercontent.com"
        )

        response = await client.get("/v1/auth/config")

        assert set(response.json()) == {"google_enabled", "google_client_id"}

    async def test_it_needs_no_session(self, client: AsyncClient) -> None:
        """It is read by the sign-in page, which by definition has no session yet."""
        response = await client.get("/v1/auth/config")

        assert response.status_code == 200
