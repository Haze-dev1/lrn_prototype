"""Response schemas for authentication and account endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.constants.enums import TargetRole


class ProfileResponse(BaseModel):
    """A student's profile and privacy state."""

    model_config = ConfigDict(from_attributes=True)

    school: str | None = None
    graduation_year: int | None = None
    target_role: TargetRole | None = None
    recruiting_consent: bool = Field(
        description="Whether the student has consented to recruiter visibility."
    )
    recruiting_consent_updated_at: datetime | None = None
    marketing_emails_opt_in: bool = False
    onboarding_completed_at: datetime | None = None


class CurrentUserResponse(BaseModel):
    """The signed-in user, as the client is allowed to see them.

    Carries no password hash, no Google subject and no refresh state. The response schema is the
    enforcement point: those fields cannot leak because they are not part of this shape.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    is_admin: bool = False
    email_verified: bool = Field(
        description="Whether the account's email address has been verified."
    )
    onboarding_complete: bool = Field(description="Whether onboarding has been completed.")
    profile: ProfileResponse | None = None


class AuthConfigResponse(BaseModel):
    """Which sign-in methods this deployment offers, and what the browser needs to use them.

    Carries the Google *client* ID, which is public by design — it is embedded in the page of
    every site that offers Google sign-in. No client secret exists in this application, and none
    would ever be returned here. Serving it from the API rather than baking a `NEXT_PUBLIC_`
    value into the web bundle keeps one source of truth: the value the API verifies tokens
    against is the same value the browser signs in with, so the two cannot drift, and changing it
    does not require rebuilding the web image.
    """

    google_enabled: bool = Field(
        description="Whether Google sign-in is configured and usable in this deployment."
    )
    google_client_id: str | None = Field(
        default=None,
        description="Google Web Application client ID, or null when Google sign-in is off.",
    )


class MessageResponse(BaseModel):
    """A simple acknowledgement for actions with no payload to return."""

    message: str


class DataExportResponse(BaseModel):
    """A complete export of one user's data."""

    exported_at: datetime
    account: dict
    profile: dict | None
    sessions: list[dict]
    attempts: list[dict]
    skill_scores: list[dict]
    grade_flags: list[dict]
