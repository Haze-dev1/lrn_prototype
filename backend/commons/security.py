"""Password hashing and token primitives.

Isolated from the auth workflow so the cryptographic choices are reviewable in one place, and so
the controllers never touch a raw hash, a signing key, or a token secret directly.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from core import logger
from core.config.settings import settings

logging = logger(__name__)

# argon2-cffi's defaults are Argon2id at 64 MiB / t=3 / p=4, which matches current OWASP guidance.
# They are used rather than hand-tuned so the parameters track the library's security updates.
_password_hasher = PasswordHasher()

# A precomputed hash of a value nobody can supply, used to spend the same CPU time on a login for
# an address that does not exist as for one that does. Without it, response timing tells an
# attacker which email addresses are registered.
_DUMMY_HASH = _password_hasher.hash(secrets.token_urlsafe(32))

ACCESS_TOKEN_TYPE = "access"  # noqa: S105 — a JWT claim value, not a credential


def hash_password(password: str) -> str:
    """
    Hash a plaintext password with Argon2id.

    Args:
        password: The plaintext password.

    Returns:
        str: An encoded Argon2 hash including its parameters and salt.
    """
    return _password_hasher.hash(password)


def verify_password(*, password: str, password_hash: str | None) -> bool:
    """
    Check a password against a stored hash in constant-ish time.

    When no hash is supplied — an account that only ever signed in with Google, or an email that
    does not exist — a dummy verification still runs, so the response takes the same time either
    way and cannot be used to enumerate accounts.

    Args:
        password: The submitted plaintext password.
        password_hash: The stored hash, or None when there is none.

    Returns:
        bool: True when the password matches.
    """
    if password_hash is None:
        try:
            _password_hasher.verify(_DUMMY_HASH, password)
        except (VerifyMismatchError, InvalidHashError):
            pass
        return False

    try:
        _password_hasher.verify(password_hash, password)
        return True
    except (VerifyMismatchError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """
    Report whether a stored hash was made with outdated parameters.

    Lets a successful login transparently upgrade an old hash as the library's defaults harden.

    Args:
        password_hash: The stored hash.

    Returns:
        bool: True when the hash should be recomputed.
    """
    try:
        return _password_hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def create_access_token(*, user_id: uuid.UUID) -> tuple[str, datetime]:
    """
    Mint a short-lived signed access token for a user.

    Carries only the subject, type and timing claims. Authorisation facts such as admin rights and
    account status are deliberately excluded: they are read from the database on each request, so
    suspending an account takes effect immediately rather than at the next token expiry.

    Args:
        user_id: The authenticated user's ID.

    Returns:
        tuple[str, datetime]: The encoded token and its expiry time.
    """
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "typ": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def decode_access_token(token: str) -> uuid.UUID | None:
    """
    Verify an access token and return the user it identifies.

    The algorithm is pinned to the configured one so a token claiming ``alg: none`` — or any other
    algorithm — is rejected rather than trusted. Returns None on any failure so callers cannot
    accidentally distinguish "expired" from "forged" in a response.

    Args:
        token: The encoded access token.

    Returns:
        uuid.UUID | None: The subject user ID, or None when the token is not valid.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.PyJWTError:
        return None

    if payload.get("typ") != ACCESS_TOKEN_TYPE:
        # A refresh token must never be accepted as an access token.
        return None

    try:
        return uuid.UUID(str(payload["sub"]))
    except (KeyError, ValueError):
        return None


def generate_refresh_token() -> str:
    """
    Generate a high-entropy opaque refresh token.

    Opaque rather than a JWT because a refresh token must be revocable: validity is decided by the
    stored record, not by a signature the server cannot take back.

    Returns:
        str: A URL-safe random token.
    """
    return secrets.token_urlsafe(48)


def hash_refresh_token(token: str) -> str:
    """
    Hash a refresh token for storage.

    SHA-256 rather than Argon2: the token is 384 bits of server-generated randomness, so it is not
    guessable and needs no key-stretching, and refresh happens often enough that a deliberately
    slow hash would be a real latency cost. Storing the hash means a database disclosure does not
    hand out usable sessions.

    Args:
        token: The raw refresh token.

    Returns:
        str: Hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
