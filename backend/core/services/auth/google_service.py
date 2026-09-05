"""Google sign-in via ID token verification.

The browser obtains an ID token from Google and posts it here; the server verifies its signature
against Google's published keys. This avoids holding a client secret and avoids a redirect flow
with server-side state, while keeping the trust decision entirely server-side — the client only
carries a token it cannot forge.
"""

from typing import Any

import jwt
from jwt import PyJWKClient

from core import logger
from core.config.settings import settings

logging = logger(__name__)

GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")

# Cached across requests: Google's signing keys rotate slowly, and refetching them on every
# sign-in would add a network round trip and make Google's availability our availability.
_jwk_client: PyJWKClient | None = None


def _get_jwk_client() -> PyJWKClient:
    """
    Return the cached JWKS client for Google's signing keys.

    Returns:
        PyJWKClient: Client that fetches and caches Google's public keys.
    """
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(GOOGLE_JWKS_URI, cache_keys=True, timeout=10)
    return _jwk_client


class GoogleIdentityError(Exception):
    """Raised when a Google ID token cannot be verified or lacks a usable identity."""


class GoogleIdentityService:
    """Verifies Google ID tokens and extracts the identity they assert."""

    async def verify_id_token(self, *, id_token: str) -> dict[str, Any]:
        """
        Verify a Google ID token and return the identity it asserts.

        Checks the signature against Google's current keys, and that the token was issued by
        Google for this application. Verifying the audience is what stops a token minted for a
        different site being replayed here to impersonate its owner.

        Args:
            id_token: The ID token supplied by the client.

        Returns:
            dict[str, Any]: Identity fields — ``sub``, ``email``, ``email_verified``, ``name``.

        Raises:
            GoogleIdentityError: If Google sign-in is not configured, the token fails
                verification, or the token carries no verified email address.
        """
        if not settings.google_enabled:
            logging.warning("Google sign-in attempted while GOOGLE_CLIENT_ID is not configured")
            raise GoogleIdentityError("Google sign-in is not configured")

        try:
            signing_key = _get_jwk_client().get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.GOOGLE_CLIENT_ID,
                issuer=list(GOOGLE_ISSUERS),
                options={"require": ["exp", "iat", "sub", "aud", "iss"]},
            )
        except Exception as error:
            # The reason is logged but never returned: a caller probing with crafted tokens should
            # not learn which check failed.
            logging.warning(f"Google ID token verification failed: {error}")
            raise GoogleIdentityError("Could not verify Google sign-in") from error

        subject = claims.get("sub")
        email = claims.get("email")
        if not subject or not email:
            logging.warning("Google ID token verified but carried no subject or email")
            raise GoogleIdentityError("Google sign-in did not provide an email address")

        if not claims.get("email_verified", False):
            # An unverified Google email could belong to someone else, and accepting it would let
            # an attacker claim an existing LRN account by asserting its address.
            logging.warning("Rejected Google sign-in with an unverified email address")
            raise GoogleIdentityError("Your Google email address is not verified")

        return {
            "sub": str(subject),
            "email": str(email).strip().lower(),
            "email_verified": True,
            "name": claims.get("name"),
        }
