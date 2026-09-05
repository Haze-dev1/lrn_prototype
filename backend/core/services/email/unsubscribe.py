"""One-click unsubscribe tokens.

An unsubscribe link has to work without a session. A student who no longer wants these emails
must not have to remember a password to say so — making them sign in to stop mail is how a
product gets marked as spam instead of unsubscribed from.

The token is an HMAC over the user ID and a purpose, keyed by the application's signing secret.
Nothing is stored: the token is verifiable from the secret alone, so there is no table to grow, no
row to expire, and no lookup on a public endpoint. It deliberately never expires — a link in a
six-month-old email must still work, and an attacker who forges one can only *stop* mail to an
address they cannot read, which is not an attack worth defending against with an expiry that would
break real unsubscribes.

The purpose is inside the signature, so a token minted for study reminders cannot be replayed to
change any other preference.
"""

import hashlib
import hmac
import uuid
from base64 import urlsafe_b64encode

from core import logger
from core.config.settings import settings

logging = logger(__name__)

#: The only preference an emailed link may change. Declared as a constant so a future caller
#: cannot widen the endpoint's power by passing a different string.
STUDY_REMINDERS = "study_reminders"

_SIGNATURE_BYTES = 16


def _signature(*, user_id: uuid.UUID, purpose: str) -> str:
    """
    Compute the signature for one user and purpose.

    Args:
        user_id: The recipient.
        purpose: What the token permits changing.

    Returns:
        str: URL-safe signature.
    """
    message = f"{purpose}:{user_id}".encode()
    digest = hmac.new(settings.JWT_SECRET.encode(), message, hashlib.sha256).digest()
    return urlsafe_b64encode(digest[:_SIGNATURE_BYTES]).decode().rstrip("=")


def mint_token(*, user_id: uuid.UUID, purpose: str = STUDY_REMINDERS) -> str:
    """
    Build an unsubscribe token for one recipient.

    Args:
        user_id: The recipient.
        purpose: The preference the token may change.

    Returns:
        str: Token to place in an unsubscribe URL.
    """
    return f"{user_id}.{_signature(user_id=user_id, purpose=purpose)}"


def verify_token(token: str, *, purpose: str = STUDY_REMINDERS) -> uuid.UUID | None:
    """
    Recover the recipient from a token, or reject it.

    Compared with ``compare_digest`` rather than ``==``: the endpoint is public and unauthenticated,
    which is exactly the setting where a timing difference is measurable.

    Args:
        token: Token from the unsubscribe link.
        purpose: The preference the caller intends to change.

    Returns:
        uuid.UUID | None: The recipient, or None when the token is malformed or unsigned.
    """
    raw_user_id, separator, provided = token.partition(".")
    if not separator or not provided:
        return None
    try:
        user_id = uuid.UUID(raw_user_id)
    except ValueError:
        return None

    expected = _signature(user_id=user_id, purpose=purpose)
    if not hmac.compare_digest(expected, provided):
        logging.warning("Rejected an unsubscribe token with an invalid signature")
        return None
    return user_id


def unsubscribe_url(*, user_id: uuid.UUID, purpose: str = STUDY_REMINDERS) -> str:
    """
    Build the full unsubscribe link for an email.

    Args:
        user_id: The recipient.
        purpose: The preference the link may change.

    Returns:
        str: Absolute URL for the ``List-Unsubscribe`` header and the message footer.
    """
    base = settings.PUBLIC_WEB_URL.rstrip("/")
    return f"{base}/unsubscribe?token={mint_token(user_id=user_id, purpose=purpose)}"
