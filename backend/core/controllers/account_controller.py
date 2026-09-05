"""Profile, onboarding, consent, and account data controls."""

from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete as sql_delete

from commons.security import verify_password
from core import logger
from core.cruds.attempt_crud import CRUDAttempt, CRUDGradeFlag
from core.cruds.auth_crud import CRUDRefreshToken
from core.cruds.session_crud import CRUDSession
from core.cruds.skill_score_crud import CRUDSkillScore
from core.cruds.user_crud import CRUDProfile, CRUDUser
from core.database.database import session
from core.models.user_model import User

logging = logger(__name__)

# Bounds the export so a single request cannot try to serialise an unbounded history into memory.
MAX_EXPORT_ROWS = 5000


class AccountController:
    """Owns profile editing, consent, data export, and account deletion."""

    def __init__(self) -> None:
        """Initialise the controller with the CRUD layers it coordinates."""
        self.CRUDUser = CRUDUser()
        self.CRUDProfile = CRUDProfile()
        self.CRUDSession = CRUDSession()
        self.CRUDAttempt = CRUDAttempt()
        self.CRUDSkillScore = CRUDSkillScore()
        self.CRUDGradeFlag = CRUDGradeFlag()
        self.CRUDRefreshToken = CRUDRefreshToken()

    async def complete_onboarding(self, *, user: User, payload: dict[str, Any]) -> dict:
        """
        Record onboarding answers and mark onboarding complete.

        Idempotent: re-submitting updates the answers without resetting the original completion
        time, so a student editing their school later does not appear to have just onboarded.

        Args:
            user: The authenticated user.
            payload: Validated onboarding fields.

        Returns:
            dict: The updated profile.

        Raises:
            HTTPException 404: The user has no profile record.
            HTTPException 500: Unexpected failure saving onboarding.
        """
        try:
            logging.info("Executing AccountController.complete_onboarding")
            existing = await self.CRUDProfile.get_by_user_id(user_id=user.id)
            if existing is None:
                # Every account gets a profile at registration, so this means inconsistent data.
                logging.error(f"No profile record exists for user {user.id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
                )

            updates = dict(payload)
            if existing.onboarding_completed_at is None:
                updates["onboarding_completed_at"] = datetime.now(UTC)

            profile = await self.CRUDProfile.update(user_id=user.id, obj_in=updates)
            logging.info(f"Onboarding saved for user {user.id}")
            return {"profile": profile}
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AccountController.complete_onboarding: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal Server Error",
            ) from error

    async def update_profile(self, *, user: User, payload: dict[str, Any]) -> dict:
        """
        Update editable profile fields.

        Only fields the caller actually sent are written, so a partial update cannot blank out
        values it did not mention. Consent is not accepted here — it has its own endpoint.

        Args:
            user: The authenticated user.
            payload: Validated profile fields, possibly partial.

        Returns:
            dict: The updated profile.

        Raises:
            HTTPException 400: No editable fields were supplied.
            HTTPException 404: The user has no profile record.
            HTTPException 500: Unexpected failure saving the profile.
        """
        try:
            logging.info("Executing AccountController.update_profile")
            updates = {key: value for key, value in payload.items() if value is not None}
            updates.pop("recruiting_consent", None)
            if not updates:
                logging.warning(f"Profile update for user {user.id} contained no fields")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="No changes supplied"
                )

            profile = await self.CRUDProfile.update(user_id=user.id, obj_in=updates)
            if profile is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
                )
            return {"profile": profile}
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AccountController.update_profile: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal Server Error",
            ) from error

    async def set_recruiting_consent(self, *, user: User, granted: bool) -> dict:
        """
        Grant or withdraw recruiting consent.

        Its own operation so consent is always a deliberate act rather than a field carried along
        by an unrelated save. The CRUD layer stamps the change time, making it auditable, and the
        same path withdraws it, making it revocable.

        Args:
            user: The authenticated user.
            granted: Whether consent is being granted.

        Returns:
            dict: The updated profile.

        Raises:
            HTTPException 404: The user has no profile record.
            HTTPException 500: Unexpected failure saving consent.
        """
        try:
            logging.info("Executing AccountController.set_recruiting_consent")
            profile = await self.CRUDProfile.update(
                user_id=user.id, obj_in={"recruiting_consent": granted}
            )
            if profile is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
                )
            logging.info(
                f"Recruiting consent {'granted' if granted else 'withdrawn'} by user {user.id}"
            )
            return {"profile": profile}
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AccountController.set_recruiting_consent: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal Server Error",
            ) from error

    async def export_data(self, *, user: User) -> dict:
        """
        Assemble a complete export of the user's own data.

        Includes the answers they wrote and the grades they received, because that is the record
        they are entitled to. Excludes anything that is not theirs — ideal answers, rubrics, and
        raw model responses — since an export must not become a route around question protection.

        Args:
            user: The authenticated user.

        Returns:
            dict: The user's exportable data.

        Raises:
            HTTPException 500: Unexpected failure assembling the export.
        """
        try:
            logging.info("Executing AccountController.export_data")
            profile = await self.CRUDProfile.get_by_user_id(user_id=user.id)
            sessions = await self.CRUDSession.list_for_user(user_id=user.id, limit=MAX_EXPORT_ROWS)
            attempts = await self.CRUDAttempt.list_for_user(user_id=user.id, limit=MAX_EXPORT_ROWS)
            scores = await self.CRUDSkillScore.list_for_user(user_id=user.id)

            return {
                "exported_at": datetime.now(UTC),
                "account": {
                    "id": str(user.id),
                    "email": user.email,
                    "created_at": user.created_at.isoformat(),
                    "email_verified": user.email_verified_at is not None,
                    "has_password": user.password_hash is not None,
                    "linked_google_account": user.google_sub is not None,
                },
                "profile": None
                if profile is None
                else {
                    "school": profile.school,
                    "graduation_year": profile.graduation_year,
                    "target_role": profile.target_role,
                    "recruiting_consent": profile.recruiting_consent,
                    "recruiting_consent_updated_at": (
                        profile.recruiting_consent_updated_at.isoformat()
                        if profile.recruiting_consent_updated_at
                        else None
                    ),
                    "onboarding_completed_at": (
                        profile.onboarding_completed_at.isoformat()
                        if profile.onboarding_completed_at
                        else None
                    ),
                },
                "sessions": [
                    {
                        "id": str(row.id),
                        "type": row.type,
                        "status": row.status,
                        "question_count": row.question_count,
                        "started_at": row.started_at.isoformat(),
                        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                    }
                    for row in sessions
                ],
                "attempts": [
                    {
                        "id": str(row.id),
                        "session_id": str(row.session_id),
                        "answer": row.answer,
                        "grading_status": row.grading_status,
                        "score": row.score,
                        "band": row.band,
                        "feedback": row.feedback,
                        "concepts_hit": row.concepts_hit,
                        "concepts_missed": row.concepts_missed,
                        "mistake_flags": row.mistake_flags,
                        "submitted_at": row.submitted_at.isoformat(),
                    }
                    for row in attempts
                ],
                "skill_scores": [
                    {
                        "category": row.category_slug,
                        "score": row.score,
                        "previous_score": row.previous_score,
                        "evidence_count": row.evidence_count,
                        "calculated_at": row.calculated_at.isoformat(),
                    }
                    for row in scores
                ],
                "grade_flags": [],
            }
        except Exception as error:
            logging.error(f"Error in AccountController.export_data: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal Server Error",
            ) from error

    async def delete_account(self, *, user: User, password: str | None) -> dict:
        """
        Permanently delete the account and everything belonging to it.

        Password-backed accounts must re-enter their password, so an unlocked browser is not
        enough to destroy someone's history. The row is deleted outright rather than flagged: the
        foreign keys cascade to profile, sessions, attempts, grades and mastery, which is what
        makes the deletion real rather than cosmetic.

        Args:
            user: The authenticated user.
            password: Current password, required when the account has one.

        Returns:
            dict: An acknowledgement message.

        Raises:
            HTTPException 400: A password is required and was not supplied.
            HTTPException 401: The supplied password is not correct.
            HTTPException 500: Unexpected failure deleting the account.
        """
        try:
            logging.info("Executing AccountController.delete_account")
            if user.password_hash is not None:
                if not password:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Enter your password to confirm deletion",
                    )
                if not verify_password(password=password, password_hash=user.password_hash):
                    logging.warning(f"Account deletion refused, wrong password for {user.id}")
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Incorrect password",
                    )

            await self.CRUDRefreshToken.revoke_all_for_user(user_id=user.id)

            async with session() as db:
                await db.execute(sql_delete(User).where(User.id == user.id))

            logging.info(f"Account {user.id} permanently deleted")
            return {"message": "Your account and all associated data have been deleted"}
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AccountController.delete_account: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Internal Server Error",
            ) from error
