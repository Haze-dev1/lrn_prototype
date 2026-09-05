"""The email provider boundary.

Everything above this line renders a message; everything below it delivers one. Swapping Resend
for another sender should touch one implementation file.

Unlike the payment provider, a local fake is safe here and is the default. A fake grade is
obviously local and a fake payment would be indistinguishable from a real one — but an email that
was never sent grants nothing, costs nothing, and is exactly what a test and a fresh clone want.
"""

from abc import ABC, abstractmethod

from core import logger
from core.config.settings import settings
from core.services.email.types import EmailMessage, SendResult

logging = logger(__name__)


class EmailProvider(ABC):
    """Delivers a rendered message."""

    #: Stable identifier recorded in the log line for every send.
    name: str

    @abstractmethod
    async def send(self, message: EmailMessage) -> SendResult:
        """
        Deliver one message.

        Returns a result rather than raising for an ordinary delivery failure, because every
        caller treats a failed send the same way — log it and let the sweep try again — and an
        exception would make that the caller's problem to remember.

        Args:
            message: The rendered message.

        Returns:
            SendResult: Whether it was delivered, and the provider's identifier or error.
        """


def get_email_provider() -> EmailProvider:
    """
    Build the email provider named by configuration.

    Imports are local to the branch taken, so a deployment configured for one provider does not
    import the other's client.

    Returns:
        EmailProvider: The configured provider.
    """
    if settings.EMAIL_PROVIDER == "resend" and settings.RESEND_API_KEY:
        from core.services.email.resend_provider import ResendProvider

        return ResendProvider()

    if settings.EMAIL_PROVIDER == "resend":
        # Configured to send but missing the credential to do it. Falling back to the log provider
        # keeps the application running, and the warning is what makes the misconfiguration
        # visible rather than silent.
        logging.warning("EMAIL_PROVIDER is 'resend' but no API key is configured; logging instead")

    from core.services.email.log_provider import LogEmailProvider

    return LogEmailProvider()
