"""Email preference orchestration.

Small, but it owns one rule that matters: an emailed unsubscribe link can only ever turn a
preference **off**. The token proves who the recipient is, not what they want — so the endpoint
does not take a value from the caller and does not let a link be reused to turn anything back on.
Re-subscribing requires signing in, which is the correct asymmetry: stopping unwanted mail should
be as easy as possible, and starting it should not.
"""

from typing import Any

from fastapi import HTTPException, status

from core import logger
from core.cruds.user_crud import CRUDProfile
from core.models.user_model import User
from core.services.email.unsubscribe import verify_token

logging = logger(__name__)


class EmailController:
    """Reads and updates a student's email preferences."""

    def __init__(self) -> None:
        """Initialise the controller with the CRUD layer it coordinates."""
        self.CRUDProfile = CRUDProfile()

    async def get_preferences(self, *, user: User) -> dict[str, Any]:
        """
        Read the caller's email preferences.

        Falls back to the defaults rather than failing when a profile row is missing — an account
        without one is still entitled to an answer about what it will receive.

        Args:
            user: The authenticated caller.

        Returns:
            dict[str, Any]: Current preferences.

        Raises:
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing EmailController.get_preferences")
            profile = await self.CRUDProfile.get_by_user_id(user_id=user.id)
            return {
                "study_reminder_emails": profile.study_reminder_emails if profile else True,
                "marketing_emails_opt_in": profile.marketing_emails_opt_in if profile else False,
            }
        except Exception as error:
            logging.error(f"Error in EmailController.get_preferences: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def set_preferences(
        self, *, user: User, study_reminder_emails: bool, marketing_emails_opt_in: bool
    ) -> dict[str, Any]:
        """
        Update the caller's email preferences.

        Args:
            user: The authenticated caller.
            study_reminder_emails: Whether to receive weekly weak-area reminders.
            marketing_emails_opt_in: Whether to receive product news.

        Returns:
            dict[str, Any]: The stored preferences.

        Raises:
            HTTPException 404: The caller has no profile to update.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing EmailController.set_preferences")
            profile = await self.CRUDProfile.update(
                user_id=user.id,
                obj_in={
                    "study_reminder_emails": study_reminder_emails,
                    "marketing_emails_opt_in": marketing_emails_opt_in,
                },
            )
            if profile is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
                )
            logging.info(f"Updated email preferences for user {user.id}")
            return {
                "study_reminder_emails": profile.study_reminder_emails,
                "marketing_emails_opt_in": profile.marketing_emails_opt_in,
            }
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in EmailController.set_preferences: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def unsubscribe(self, *, token: str) -> bool:
        """
        Turn study reminders off for the recipient a signed token names.

        Writes ``False`` rather than a value supplied by the caller, so a link can only ever stop
        mail. An invalid token is answered like a valid one by the route above — this returns the
        outcome for the log, not for the response.

        Args:
            token: The signed token from an emailed link.

        Returns:
            bool: True when a profile was actually updated.

        Raises:
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing EmailController.unsubscribe")
            user_id = verify_token(token)
            if user_id is None:
                return False

            profile = await self.CRUDProfile.update(
                user_id=user_id, obj_in={"study_reminder_emails": False}
            )
            if profile is None:
                logging.warning("Unsubscribe token names an account with no profile")
                return False

            logging.info(f"Study reminders turned off for user {user_id} via an emailed link")
            return True
        except Exception as error:
            logging.error(f"Error in EmailController.unsubscribe: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error
