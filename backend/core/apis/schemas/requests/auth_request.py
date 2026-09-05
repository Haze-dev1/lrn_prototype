"""Request schemas for authentication and account endpoints."""

from pydantic import BaseModel, EmailStr, Field, field_validator

from core.constants.enums import TargetRole

# Long enough to resist offline guessing, with no composition rules: forced character classes
# push people toward predictable substitutions without materially raising entropy.
MIN_PASSWORD_LENGTH = 10
# Argon2 has no practical input limit, but an unbounded password is a cheap way to make the
# server burn memory hashing megabytes.
MAX_PASSWORD_LENGTH = 256


class RegisterRequest(BaseModel):
    """Payload for creating an account with an email and password."""

    email: EmailStr = Field(description="Email address used to sign in.")
    password: str = Field(
        min_length=MIN_PASSWORD_LENGTH,
        max_length=MAX_PASSWORD_LENGTH,
        description=f"Password, at least {MIN_PASSWORD_LENGTH} characters.",
    )

    @field_validator("password")
    @classmethod
    def _reject_whitespace_only(cls, value: str) -> str:
        """
        Reject a password made only of whitespace.

        The length rule alone would accept ten spaces, which is trivially guessable.

        Args:
            value: The submitted password.

        Returns:
            str: The password, unchanged.

        Raises:
            ValueError: If the password contains no non-whitespace characters.
        """
        if not value.strip():
            raise ValueError("Password must contain more than whitespace")
        return value


class LoginRequest(BaseModel):
    """Payload for signing in with an email and password."""

    email: EmailStr = Field(description="Email address used to sign in.")
    password: str = Field(
        min_length=1, max_length=MAX_PASSWORD_LENGTH, description="Account password."
    )


class GoogleSignInRequest(BaseModel):
    """Payload for signing in with a Google ID token."""

    id_token: str = Field(
        min_length=1, max_length=8192, description="ID token issued by Google to the browser."
    )


class OnboardingRequest(BaseModel):
    """Payload completing onboarding.

    Recruiting consent is deliberately absent: it is never bundled with another action, so it can
    only ever be granted by an explicit, separate choice.
    """

    school: str = Field(min_length=1, max_length=200, description="University or school name.")
    graduation_year: int = Field(ge=1950, le=2100, description="Expected graduation year.")
    target_role: TargetRole = Field(description="Recruiting track: IB, PE, or both.")


class ProfileUpdateRequest(BaseModel):
    """Payload for editing profile fields after onboarding."""

    school: str | None = Field(default=None, min_length=1, max_length=200)
    graduation_year: int | None = Field(default=None, ge=1950, le=2100)
    target_role: TargetRole | None = None
    marketing_emails_opt_in: bool | None = None


class ConsentUpdateRequest(BaseModel):
    """Payload for granting or withdrawing recruiting consent.

    Its own endpoint and its own schema so consent is always a deliberate act, never a field that
    rides along with an unrelated profile save.
    """

    recruiting_consent: bool = Field(
        description="Whether the student consents to recruiter visibility."
    )


class AccountDeletionRequest(BaseModel):
    """Payload confirming permanent account deletion."""

    confirmation: str = Field(
        description="Must be the literal string 'DELETE' to proceed.",
    )
    # Required for password accounts so a walk-up attacker at an unlocked browser cannot delete
    # the account with a single click.
    password: str | None = Field(
        default=None, max_length=MAX_PASSWORD_LENGTH, description="Current password."
    )

    @field_validator("confirmation")
    @classmethod
    def _must_confirm(cls, value: str) -> str:
        """
        Require the exact confirmation phrase.

        Args:
            value: The submitted confirmation string.

        Returns:
            str: The confirmation, unchanged.

        Raises:
            ValueError: If the phrase does not match.
        """
        if value != "DELETE":
            raise ValueError("Type DELETE to confirm account deletion")
        return value
