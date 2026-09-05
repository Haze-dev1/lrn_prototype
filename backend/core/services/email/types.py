"""The email domain boundary.

An ``EmailMessage`` is everything a provider needs and nothing it does not: no user object, no
database row, no template name. Rendering happens above this line, sending happens below it, and
neither side has to know how the other works.
"""

from dataclasses import dataclass
from enum import StrEnum


class EmailKind(StrEnum):
    """What an email is, which decides whether a student can turn it off.

    Transactional messages are consequences of something the student did and are not subject to a
    preference: someone who finished a diagnostic is owed their results, and someone who paid is
    owed a receipt. Lifecycle messages are sent on the product's initiative, and every one of them
    must be refusable.
    """

    DIAGNOSTIC_RESULTS = "diagnostic_results"
    PAYMENT_RECEIPT = "payment_receipt"
    WEAK_AREA_NUDGE = "weak_area_nudge"

    @property
    def is_lifecycle(self) -> bool:
        """
        Report whether this kind may be switched off by the recipient.

        Returns:
            bool: True for messages the product initiates rather than the student.
        """
        return self is EmailKind.WEAK_AREA_NUDGE


@dataclass(frozen=True)
class EmailMessage:
    """One rendered message, ready to send.

    Both bodies are required. A text alternative is not a courtesy — a message with only HTML is
    scored as more likely to be spam, and the students receiving these are reading on university
    mail systems that are stricter than most.
    """

    to: str
    subject: str
    html: str
    text: str
    kind: EmailKind
    #: Value for the ``List-Unsubscribe`` headers. Set for lifecycle mail, absent otherwise.
    unsubscribe_url: str | None = None


@dataclass(frozen=True)
class SendResult:
    """What happened when a message was handed to the provider."""

    delivered: bool
    provider_message_id: str | None = None
    error: str | None = None
