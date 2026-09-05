"""Authentication dependencies for FastAPI routes.

Every protected endpoint resolves its caller through these dependencies, so identity is
established in exactly one place. The token is read from an HttpOnly cookie rather than a header:
the browser cannot read it, which removes the token-exfiltration path that scripted XSS relies on.
"""

from fastapi import Depends, HTTPException, Request, status

from commons.security import decode_access_token
from core import logger
from core.config.settings import settings
from core.constants.enums import UserStatus
from core.cruds.user_crud import CRUDUser
from core.models.user_model import User

logging = logger(__name__)


async def get_current_user(request: Request) -> User:
    """
    Resolve and validate the caller from their access token cookie.

    The user record is loaded on every request rather than trusted from token claims, so a
    suspended or deleted account loses access immediately instead of at the next token expiry.
    That is a primary-key lookup, which is cheap enough to prefer over a stale-authorisation
    window.

    Args:
        request: The incoming request, carrying the access cookie.

    Returns:
        User: The authenticated, active user.

    Raises:
        HTTPException 401: No token, an invalid token, or a user that no longer exists.
        HTTPException 403: The account exists but is not active.
    """
    token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user_id = decode_access_token(token)
    if user_id is None:
        logging.warning("Rejected a request carrying an invalid or expired access token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    user = await CRUDUser().get_by_id(user_id=user_id)
    if user is None:
        # The token verified but its subject is gone — a deleted account presenting a token that
        # has not yet expired.
        logging.warning(f"Access token references a user that no longer exists: {user_id}")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    if user.status != UserStatus.ACTIVE:
        logging.warning(f"Rejected request from non-active user {user.id} ({user.status})")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="This account is not active"
        )

    return user


async def get_optional_user(request: Request) -> User | None:
    """
    Resolve the caller when signed in, without requiring it.

    For endpoints that render differently for a signed-in visitor but remain public.

    Args:
        request: The incoming request.

    Returns:
        User | None: The authenticated active user, or None.
    """
    try:
        return await get_current_user(request)
    except HTTPException:
        return None


async def require_admin(user: User = Depends(get_current_user)) -> User:
    """
    Require that the caller is an administrator.

    Deliberately returns 404 rather than 403 for a signed-in non-admin, so the existence of admin
    endpoints is not confirmed to an ordinary user probing the API.

    Args:
        user: The authenticated user, resolved by ``get_current_user``.

    Returns:
        User: The authenticated administrator.

    Raises:
        HTTPException 404: The caller is not an administrator.
    """
    if not user.is_admin:
        logging.warning(f"Non-admin user {user.id} attempted to reach an admin endpoint")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return user


def client_identifier(request: Request) -> str:
    """
    Derive a rate-limiting identifier for the caller.

    Prefers the proxy's forwarded client address, falling back to the socket peer. This is only
    used for abuse control, never for authorisation, because a header can be forged by anything
    between the client and the proxy.

    Args:
        request: The incoming request.

    Returns:
        str: An identifier suitable for a rate-limit key.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
