"""The Resend adapter — the only module that knows how mail actually leaves this system.

Resend's send endpoint is a single JSON POST, so this uses ``httpx`` directly rather than adding
an SDK for one call. Everything Resend-specific lives here: the field names, the header shape, and
the identifier it returns.
"""

from typing import Any

import httpx

from core import logger
from core.config.settings import settings
from core.services.email.provider import EmailProvider
from core.services.email.types import EmailMessage, SendResult

logging = logger(__name__)


class ResendProvider(EmailProvider):
    """Delivers mail through Resend's HTTP API."""

    name = "resend"

    async def send(self, message: EmailMessage) -> SendResult:
        """
        Deliver one message through Resend.

        Never raises. A delivery failure is an ordinary outcome — the recipient's server is down,
        the API is rate limiting, the network blipped — and the callers above all respond to it
        the same way: leave the send marker unset so the next sweep tries again.

        Args:
            message: The rendered message.

        Returns:
            SendResult: Delivery outcome, with Resend's message ID or the failure reason.
        """
        payload: dict[str, Any] = {
            "from": settings.EMAIL_FROM,
            "to": [message.to],
            "subject": message.subject,
            "html": message.html,
            "text": message.text,
        }
        if settings.EMAIL_REPLY_TO:
            payload["reply_to"] = settings.EMAIL_REPLY_TO
        if message.unsubscribe_url:
            # Both headers, deliberately. `List-Unsubscribe` alone leaves the mail client asking
            # the reader to confirm; adding `List-Unsubscribe-Post` is what turns it into the
            # one-click control Gmail and Outlook render at the top of the message, and one-click
            # unsubscribes are the difference between being unsubscribed from and being reported
            # as spam.
            payload["headers"] = {
                "List-Unsubscribe": f"<{message.unsubscribe_url}>",
                "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
            }

        try:
            async with httpx.AsyncClient(
                base_url=settings.RESEND_BASE_URL, timeout=settings.EMAIL_TIMEOUT_SECONDS
            ) as client:
                response = await client.post(
                    "/emails",
                    json=payload,
                    headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
                )
            if response.status_code >= 400:
                # The response body is logged, not the payload: the payload contains the student's
                # scores and the message we rendered for them.
                logging.error(
                    f"Resend rejected a {message.kind} email with {response.status_code}: "
                    f"{response.text[:300]}"
                )
                return SendResult(delivered=False, error=f"HTTP {response.status_code}")

            body = response.json()
            identifier = body.get("id") if isinstance(body, dict) else None
            logging.info(f"Sent a {message.kind} email, provider id {identifier}")
            return SendResult(delivered=True, provider_message_id=identifier)
        except Exception as error:
            logging.error(f"Error in ResendProvider.send: {error}")
            return SendResult(delivered=False, error=str(error)[:300])
