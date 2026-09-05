"""Database access for per-category mastery scores."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from core import logger
from core.database.database import session
from core.models.skill_score_model import SkillScore

logging = logger(__name__)


class CRUDSkillScore:
    """Database access layer for mastery scores."""

    async def upsert(
        self,
        *,
        user_id: uuid.UUID,
        category_slug: str,
        score: int,
        evidence_count: int,
        last_attempt_at: datetime | None = None,
    ) -> SkillScore:
        """
        Insert or update a user's mastery score for one category.

        Uses a single ON CONFLICT statement rather than a read-then-write. The nightly rollup and
        an on-demand recalculation can run concurrently, and a read-then-write would let one
        silently overwrite the other's result. The previous score is carried forward from the row
        being replaced, so the interface can show movement without re-deriving history.

        Args:
            user_id: Owning user ID.
            category_slug: Category the score belongs to.
            score: New mastery value, 0-100.
            evidence_count: Number of graded attempts backing the score.
            last_attempt_at: Timestamp of the most recent contributing attempt.

        Returns:
            SkillScore: The stored score row.

        Raises:
            Exception: If the write fails.
        """
        try:
            logging.info("Executing CRUDSkillScore.upsert")
            now = datetime.now(UTC)
            statement = (
                insert(SkillScore)
                .values(
                    user_id=user_id,
                    category_slug=category_slug,
                    score=score,
                    evidence_count=evidence_count,
                    last_attempt_at=last_attempt_at,
                    calculated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["user_id", "category_slug"],
                    set_={
                        "score": score,
                        "previous_score": SkillScore.__table__.c.score,
                        "evidence_count": evidence_count,
                        "last_attempt_at": last_attempt_at,
                        "calculated_at": now,
                        "updated_at": now,
                    },
                )
                .returning(SkillScore)
            )
            async with session() as db:
                result = await db.execute(statement)
                return result.scalar_one()
        except Exception as error:
            logging.error(f"Error in CRUDSkillScore.upsert: {error}")
            raise error

    async def list_for_user(self, *, user_id: uuid.UUID) -> list[SkillScore]:
        """
        Read a user's mastery scores, weakest first.

        Weakest-first ordering matches how every consuming surface reads them: the dashboard
        spotlight, the results page, and practice recommendation all lead with the weakest
        category.

        Args:
            user_id: Owning user ID.

        Returns:
            list[SkillScore]: Scores ordered from lowest to highest.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSkillScore.list_for_user")
            async with session() as db:
                result = await db.execute(
                    select(SkillScore)
                    .where(SkillScore.user_id == user_id)
                    .order_by(SkillScore.score, SkillScore.category_slug)
                )
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDSkillScore.list_for_user: {error}")
            raise error

    async def get_for_category(
        self, *, user_id: uuid.UUID, category_slug: str
    ) -> SkillScore | None:
        """
        Read a user's mastery score for one category.

        Args:
            user_id: Owning user ID.
            category_slug: Category slug.

        Returns:
            SkillScore | None: The score row, or None when the category has no evidence yet.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSkillScore.get_for_category")
            async with session() as db:
                result = await db.execute(
                    select(SkillScore)
                    .where(SkillScore.user_id == user_id)
                    .where(SkillScore.category_slug == category_slug)
                )
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDSkillScore.get_for_category: {error}")
            raise error
