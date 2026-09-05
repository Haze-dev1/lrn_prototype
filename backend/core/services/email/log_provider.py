"""The default email provider: writes the message to the log and sends nothing.

This is what a fresh clone and the test suite get. It exists so that every code path that sends
email is exercised locally — the rendering, the preference checks, the delivery markers — without
any of it reaching a real inbox.

The body is logged at DEBUG rather than INFO so that ordinary log output stays readable while a
developer working on a template can still see exactly what would have gone out.
"""

from core import logger
from core.services.email.provider import EmailProvider
from core.services.email.types import EmailMessage, SendResult

logging = logger(__name__)


class LogEmailProvider(EmailProvider):
    """Records what would have been sent."""

    name = "log"

    async def send(self, message: EmailMessage) -> SendResult:
        """
        Record a message instead of delivering it.

        Args:
            message: The rendered message.

        Returns:
            SendResult: Always delivered, with a synthetic identifier.
        """
        logging.info(f"[email:log] {message.kind} to {message.to} — {message.subject!r}")
        logging.debug(f"[email:log] body\n{message.text}")
        return SendResult(delivered=True, provider_message_id=f"log:{message.kind}")
