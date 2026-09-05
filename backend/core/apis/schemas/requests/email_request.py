"""Request schemas for email preferences and analytics."""

from pydantic import BaseModel, Field

from core.services.analytics.events import PUBLIC_EVENTS


class EmailPreferencesRequest(BaseModel):
    """A student's choices about non-essential email.

    Only lifecycle mail appears here. There is no field for results or receipts, because those are
    consequences of the student's own actions and are not a mailing list to be on.
    """

    study_reminder_emails: bool = Field(
        description="Weekly weak-area reminders. On by default; refusable at any time."
    )
    marketing_emails_opt_in: bool = Field(
        default=False, description="Product news. Off unless explicitly turned on."
    )


class UnsubscribeRequest(BaseModel):
    """A one-click unsubscribe from an emailed link.

    The token carries the recipient and what it may change, so there is no user ID here to
    substitute and no preference name to widen.
    """

    token: str = Field(min_length=8, max_length=200)


class PublicEventRequest(BaseModel):
    """An event a browser is permitted to report.

    Restricted to the handful of things that genuinely only happen in a browser. Everything else
    in the funnel is recorded server-side, where the event is a consequence of work the API
    actually did — an event a client can assert is an event a client can fabricate, and
    ``checkout_completed`` from an anonymous POST would corrupt the one number the product is
    measured on.
    """

    event: str = Field(description="Event name; must be one of the public events.")

    @classmethod
    def is_permitted(cls, event: str) -> bool:
        """
        Report whether a browser may record this event.

        Args:
            event: Requested event name.

        Returns:
            bool: True when the event is on the public allowlist.
        """
        return event in PUBLIC_EVENTS
