"""Review history and progress.

Review turns graded attempts into something a student can act on. The list exists to answer
"where did I go wrong", so it is filtered by the things that make an answer worth revisiting —
category, a low score, a specific concept missed, a disputed grade — rather than by date alone.

Progress answers four questions and no others: where am I, am I improving, what am I weakest at,
and what should I do next. Anything that does not answer one of those is deliberately absent.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status

from core import logger
from core.constants.enums import GradeFlagReason
from core.cruds.attempt_crud import CRUDAttempt, CRUDGradeFlag
from core.cruds.category_crud import CRUDCategory
from core.cruds.question_crud import CRUDQuestion, CRUDQuestionVersion
from core.cruds.skill_score_crud import CRUDSkillScore
from core.models.user_model import User
from core.services.analytics.events import AnalyticsEvent
from core.services.analytics.service import track
from core.services.mastery.service import CONFIDENT_EVIDENCE_THRESHOLD, MasteryService

logging = logger(__name__)

MAX_PAGE_SIZE = 50
# How far back "recent" reaches when a student filters for it. A fortnight is roughly a study
# cycle: long enough to hold a week's work plus the one before it.
RECENT_WINDOW_DAYS = 14
# A category scoring at or below this is called weak on the progress page, matching the
# threshold the results page and the practice engine use.
WEAKNESS_THRESHOLD = 65


class ReviewController:
    """Serves a student's own graded history and their progress over time."""

    def __init__(self) -> None:
        """Initialise the controller with the CRUD layers and services it coordinates."""
        self.CRUDAttempt = CRUDAttempt()
        self.CRUDGradeFlag = CRUDGradeFlag()
        self.CRUDQuestion = CRUDQuestion()
        self.CRUDQuestionVersion = CRUDQuestionVersion()
        self.CRUDCategory = CRUDCategory()
        self.CRUDSkillScore = CRUDSkillScore()
        self.MasteryService = MasteryService()

    async def list_attempts(
        self,
        *,
        user: User,
        category_slug: str | None = None,
        max_score: int | None = None,
        missed_concept: str | None = None,
        flagged_only: bool = False,
        recent_only: bool = False,
        before: datetime | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        """
        Read a filtered page of the caller's graded attempts.

        Returns a summary per attempt — enough to decide whether to open it — and deliberately not
        the student's full answer or the reference answer. A review list is scanned, and shipping
        every answer in it would make the page heavy to load and heavy to read.

        Args:
            user: The authenticated caller.
            category_slug: Restrict to one category.
            max_score: Only attempts scoring at or below this.
            missed_concept: Only attempts that missed this concept.
            flagged_only: Only attempts the caller has disputed.
            recent_only: Only attempts from the recent window.
            before: Keyset cursor; attempts submitted before this timestamp.
            limit: Page size, capped server-side.

        Returns:
            dict[str, Any]: Page items and the cursor for the next page.

        Raises:
            HTTPException 400: An unknown category was requested.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing ReviewController.list_attempts")
            if category_slug is not None:
                if await self.CRUDCategory.get_by_slug(slug=category_slug) is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Unknown category: {category_slug}",
                    )

            page_size = max(1, min(limit, MAX_PAGE_SIZE))
            attempts = await self.CRUDAttempt.list_for_user(
                user_id=user.id,
                category_slug=category_slug,
                max_score=max_score,
                missed_concept=missed_concept,
                flagged_only=flagged_only,
                # A diagnostic in progress is not yet history, and its per-question scores stay
                # sealed until the sitting ends — the same rule the results and attempt endpoints
                # already enforce.
                exclude_unfinished_diagnostic=True,
                since=datetime.now(UTC) - timedelta(days=RECENT_WINDOW_DAYS)
                if recent_only
                else None,
                before=before,
                limit=page_size + 1,
            )
            has_more = len(attempts) > page_size
            page = attempts[:page_size]

            # One query for every flag, rather than one per row.
            flagged = await self.CRUDGradeFlag.list_attempt_ids_for_user(user_id=user.id)
            categories = {
                category.slug: category.name for category in await self.CRUDCategory.list_all()
            }

            # Two more queries for the whole page, on the same principle as the flags above:
            # a page of twenty was costing forty round trips to render twenty rows.
            question_map = await self.CRUDQuestion.map_by_ids(
                question_ids=[attempt.question_id for attempt in page]
            )
            version_map = await self.CRUDQuestionVersion.map_by_ids(
                version_ids=[attempt.question_version_id for attempt in page]
            )

            items: list[dict[str, Any]] = []
            for attempt in page:
                question = question_map.get(attempt.question_id)
                version = version_map.get(attempt.question_version_id)
                if question is None or version is None:
                    continue
                items.append(
                    {
                        "id": attempt.id,
                        "question_id": attempt.question_id,
                        "category_slug": question.category_slug,
                        "category_name": categories.get(
                            question.category_slug, question.category_slug
                        ),
                        "difficulty": question.difficulty,
                        "prompt": version.prompt,
                        "score": attempt.score,
                        "band": attempt.band,
                        "concepts_missed": attempt.concepts_missed or [],
                        "submitted_at": attempt.submitted_at,
                        "flagged": attempt.id in flagged,
                    }
                )

            # Recorded on the first page only. Paging through history is one visit to review, and
            # counting each page would make a student who scrolled look like five who opened it.
            if before is None:
                track(
                    event=AnalyticsEvent.REVIEW_OPENED,
                    user_id=user.id,
                    properties={
                        "answered_count": len(items),
                        "category_slug": category_slug,
                        # Whether they narrowed it at all, not what they searched for.
                        "filtered": any(
                            [
                                category_slug is not None,
                                max_score is not None,
                                missed_concept is not None,
                                flagged_only,
                                recent_only,
                            ]
                        ),
                    },
                )

            return {
                "items": items,
                "next_cursor": page[-1].submitted_at if has_more and page else None,
            }
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in ReviewController.list_attempts: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def flag_grade(
        self, *, user: User, attempt_id: uuid.UUID, reason: str, comment: str | None
    ) -> dict[str, Any]:
        """
        Record the caller's dispute of one of their own grades.

        A flag is a statement, not a vote: raising it twice returns the existing one rather than
        erroring or stacking, which is also what the unique constraint enforces. Only graded
        attempts can be flagged — there is nothing to dispute about a grade that does not exist.

        Args:
            user: The authenticated caller.
            attempt_id: The attempt whose grade is disputed.
            reason: Why the student thinks the grade is wrong.
            comment: Optional free text.

        Returns:
            dict[str, Any]: The flag's identity and status.

        Raises:
            HTTPException 404: No such attempt, or it belongs to another user.
            HTTPException 409: The attempt has not been graded.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing ReviewController.flag_grade")
            attempt = await self.CRUDAttempt.get_by_id(attempt_id=attempt_id)
            if attempt is None or attempt.user_id != user.id:
                logging.warning(
                    f"User {user.id} tried to flag attempt {attempt_id} they do not own"
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found"
                )
            if attempt.score is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This answer has not been graded yet",
                )

            existing = await self.CRUDGradeFlag.get_for_attempt(
                attempt_id=attempt_id, user_id=user.id
            )
            if existing is not None:
                logging.info(f"Attempt {attempt_id} is already flagged by user {user.id}")
                return {"id": existing.id, "status": existing.status, "already_flagged": True}

            flag = await self.CRUDGradeFlag.create(
                obj_in={
                    "attempt_id": attempt_id,
                    "user_id": user.id,
                    "reason": reason,
                    "comment": comment,
                }
            )
            logging.info(f"User {user.id} flagged grade on attempt {attempt_id} ({reason})")
            # The reason, never the comment. A dispute comment is the student writing about their
            # own answer, and it belongs in the flag record where an admin reads it — not in a
            # third-party analytics store.
            track(
                event=AnalyticsEvent.GRADE_FLAGGED,
                user_id=user.id,
                properties={
                    "attempt_id": attempt_id,
                    "reason": reason,
                    "score": attempt.score,
                    "band": attempt.band,
                },
            )
            return {"id": flag.id, "status": flag.status, "already_flagged": False}
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in ReviewController.flag_grade: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def progress(self, *, user: User) -> dict[str, Any]:
        """
        Assemble the caller's progress: where they are, and whether they are improving.

        Categories with no evidence are returned with a null score rather than a zero. "Not
        measured" and "measured badly" are different claims, and rendering the first as the second
        would invent a readiness signal the product has no basis for.

        Args:
            user: The authenticated caller.

        Returns:
            dict[str, Any]: Per-category mastery, the weekly trend, and headline figures.

        Raises:
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing ReviewController.progress")
            categories = await self.CRUDCategory.list_all()
            stored = {
                score.category_slug: score
                for score in await self.CRUDSkillScore.list_for_user(user_id=user.id)
            }

            rows: list[dict[str, Any]] = []
            for category in categories:
                score = stored.get(category.slug)
                rows.append(
                    {
                        "slug": category.slug,
                        "name": category.name,
                        "score": score.score if score else None,
                        "previous_score": score.previous_score if score else None,
                        "evidence_count": score.evidence_count if score else 0,
                        "last_attempt_at": score.last_attempt_at if score else None,
                        # Below the threshold the score is real but thin, and the interface should
                        # present it as provisional rather than settled.
                        "provisional": bool(
                            score and score.evidence_count < CONFIDENT_EVIDENCE_THRESHOLD
                        ),
                    }
                )

            measured = [row for row in rows if row["score"] is not None]
            trend = await self.MasteryService.trend_for_user(user_id=user.id)
            movement = self._movement(trend)

            return {
                "categories": rows,
                "trend": trend,
                "overall": round(sum(int(row["score"] or 0) for row in measured) / len(measured))
                if measured
                else None,
                "measured_categories": len(measured),
                "total_categories": len(rows),
                "total_evidence": sum(int(row["evidence_count"] or 0) for row in rows),
                "movement": movement,
                "weakest": min(measured, key=lambda row: int(row["score"] or 0))["slug"]
                if measured
                else None,
                "strongest": max(measured, key=lambda row: int(row["score"] or 0))["slug"]
                if measured
                else None,
            }
        except Exception as error:
            logging.error(f"Error in ReviewController.progress: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    @staticmethod
    def _movement(trend: list[dict[str, Any]]) -> int | None:
        """
        Report the change in overall mastery across the trend window.

        Answers "am I improving" with one number. Returns None rather than zero when there is not
        enough history to say — a flat line and no data look identical on a chart, and only one of
        them means the student has not moved.

        Args:
            trend: Weekly trend points, oldest first.

        Returns:
            int | None: Change in overall mastery, or None when it cannot be determined.
        """
        measured = [point for point in trend if point.get("overall") is not None]
        if len(measured) < 2:
            return None
        return int(measured[-1]["overall"]) - int(measured[0]["overall"])


VALID_FLAG_REASONS = tuple(reason.value for reason in GradeFlagReason)
