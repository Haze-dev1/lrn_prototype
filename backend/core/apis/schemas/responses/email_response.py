"""Response schemas for email preferences."""

from pydantic import BaseModel


class EmailPreferencesResponse(BaseModel):
    """The student's current email preferences."""

    study_reminder_emails: bool
    marketing_emails_opt_in: bool


class UnsubscribeResponse(BaseModel):
    """The outcome of a one-click unsubscribe.

    Deliberately says the same thing whether the token matched a live account or not. A public
    endpoint that distinguishes them lets anyone with a token check whether an address is still
    registered.
    """

    message: str
