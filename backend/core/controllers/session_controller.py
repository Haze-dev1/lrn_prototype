"""Diagnostic session lifecycle and results.

Owns starting a diagnostic, serving its state while a student works through it, completing it,
and assembling the results page.

Two behaviours here matter more than the rest. A student who reloads mid-diagnostic **resumes**
rather than restarting, because the composition is stored and an in-progress session is found and
returned instead of a new one being created. And results are honest about grading still being in
flight: grading is asynchronous, so a student who finishes their last answer and lands on results
a second later must see progress, not a fabricated score computed from partial evidence.
"""

import uuid
from typing import Any

from fastapi import HTTPException, status

from core import logger
from core.constants.enums import GradingStatus, SessionStatus, SessionType
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.category_crud import CRUDCategory
from core.cruds.question_crud import CRUDQuestion, CRUDQuestionVersion
from core.cruds.session_crud import CRUDSession
from core.cruds.skill_score_crud import CRUDSkillScore
from core.models.attempt_model import Attempt
from core.models.session_model import Session
from core.models.user_model import User
from core.services.analytics.events import AnalyticsEvent
from core.services.analytics.service import track
from core.services.billing.entitlement_service import EntitlementRequired, EntitlementService
from core.services.mastery.service import MasteryService
from core.services.sessions.composition_service import CompositionError, DiagnosticComposer
from core.services.sessions.practice_service import (
    PRACTICE_SET_SIZES,
    PracticeComposeError,
    PracticeComposer,
)

logging = logger(__name__)

# A category scoring at or below this is called out as a weakness on the results page.
WEAKNESS_THRESHOLD = 65
# A category scoring at or above this is called out as a strength.
STRENGTH_THRESHOLD = 75


class SessionController:
    """Starts, serves, completes and reports on diagnostic sessions."""

    def __init__(self) -> None:
        """Initialise the controller with the CRUD layers and services it coordinates."""
        self.CRUDSession = CRUDSession()
        self.CRUDAttempt = CRUDAttempt()
        self.CRUDQuestion = CRUDQuestion()
        self.CRUDQuestionVersion = CRUDQuestionVersion()
        self.CRUDCategory = CRUDCategory()
        self.CRUDSkillScore = CRUDSkillScore()
        self.DiagnosticComposer = DiagnosticComposer()
        self.PracticeComposer = PracticeComposer()
        self.MasteryService = MasteryService()
        self.EntitlementService = EntitlementService()

    async def start_diagnostic(self, *, user: User) -> tuple[Session, bool]:
        """
        Start a diagnostic, or return the one already in progress.

        Resuming is the default rather than a special case. A student who closes the tab, loses
        their connection, or comes back the next day must find the same 24 questions and the
        answers they already gave; starting fresh would discard real work and make the assessment
        feel unreliable.

        Args:
            user: The authenticated caller.

        Returns:
            tuple[Session, bool]: The session, and whether it was resumed rather than created.

        Raises:
            HTTPException 402: A free account has already used its one diagnostic.
            HTTPException 409: The question bank cannot supply a complete diagnostic.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing SessionController.start_diagnostic")
            existing = await self.CRUDSession.get_active_for_user(
                user_id=user.id, session_type=SessionType.DIAGNOSTIC
            )
            if existing is not None:
                logging.info(f"Resuming diagnostic {existing.id} for user {user.id}")
                return existing, True

            # Only reached when there is nothing to resume, so a reload mid-sitting and a
            # revisit to a finished diagnostic are never refused by this.
            await self.EntitlementService.require_new_diagnostic(user=user)

            try:
                composition, rationale = await self.DiagnosticComposer.compose(user_id=user.id)
            except CompositionError as error:
                logging.error(f"Diagnostic composition failed: {error.message}")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "The question bank does not yet have enough questions for a diagnostic."
                    ),
                ) from error

            session_row = await self.CRUDSession.create_with_questions(
                obj_in={
                    "user_id": user.id,
                    "type": SessionType.DIAGNOSTIC,
                    "status": SessionStatus.IN_PROGRESS,
                    "question_count": len(composition),
                    "configuration": {"kind": "diagnostic"},
                    "selection_rationale": rationale,
                },
                questions=composition,
            )
            logging.info(f"Created diagnostic {session_row.id} for user {user.id}")
            # Only on creation. Counting a resume as a start would make the diagnostic look
            # abandoned by everyone who ever reloaded the page.
            track(
                event=AnalyticsEvent.DIAGNOSTIC_STARTED,
                user_id=user.id,
                properties={
                    "session_id": session_row.id,
                    "question_count": session_row.question_count,
                },
            )
            return session_row, False
        except HTTPException:
            raise
        except EntitlementRequired as error:
            # 402, not 403: the caller is authenticated and permitted in principle — they have
            # reached a paid boundary. The distinction is what lets the interface show an upgrade
            # prompt rather than an access error.
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=error.as_detail()
            ) from error
        except Exception as error:
            logging.error(f"Error in SessionController.start_diagnostic: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def start_practice(
        self, *, user: User, size: int, category_slug: str | None = None
    ) -> Session:
        """
        Compose and start a practice session.

        Unlike the diagnostic there is no resume-or-create: a student choosing "10 questions on
        Valuation" is asking for a new set, and silently handing them an older half-finished one
        would be answering a different question. Any previous practice session is abandoned first,
        so the "one in progress" invariant holds and an old set does not linger as a
        resumable ghost.

        Args:
            user: The authenticated caller.
            size: Requested set size.
            category_slug: Restrict to one category when the student asked for it.

        Returns:
            Session: The created session.

        Raises:
            HTTPException 400: Unsupported set size, or an unknown category.
            HTTPException 402: The free practice allowance is used up.
            HTTPException 409: No questions are available to practise.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing SessionController.start_practice")
            # Before any work is done, and before the previous set is abandoned: a refused request
            # must leave the student exactly where they were.
            await self.EntitlementService.require_practice(user=user)

            if size not in PRACTICE_SET_SIZES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Set size must be one of {', '.join(map(str, PRACTICE_SET_SIZES))}",
                )
            if category_slug is not None:
                if await self.CRUDCategory.get_by_slug(slug=category_slug) is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Unknown category: {category_slug}",
                    )

            existing = await self.CRUDSession.get_active_for_user(
                user_id=user.id, session_type=SessionType.PRACTICE
            )
            if existing is not None:
                logging.info(f"Abandoning previous practice session {existing.id}")
                await self.CRUDSession.finish(
                    session_id=existing.id, status=SessionStatus.ABANDONED
                )

            try:
                composition, rationale = await self.PracticeComposer.compose(
                    user_id=user.id, size=size, category_slug=category_slug
                )
            except PracticeComposeError as error:
                logging.warning(f"Practice composition failed: {error.message}")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail=error.message
                ) from error

            session_row = await self.CRUDSession.create_with_questions(
                obj_in={
                    "user_id": user.id,
                    "type": SessionType.PRACTICE,
                    "status": SessionStatus.IN_PROGRESS,
                    "question_count": len(composition),
                    "configuration": {
                        "kind": "practice",
                        "requested_size": size,
                        "category_slug": category_slug,
                    },
                    "selection_rationale": rationale,
                },
                questions=composition,
            )
            logging.info(f"Created practice session {session_row.id} for user {user.id}")
            rationale = session_row.selection_rationale or {}
            track(
                event=AnalyticsEvent.PRACTICE_STARTED,
                user_id=user.id,
                properties={
                    "session_id": session_row.id,
                    "requested_size": size,
                    "question_count": session_row.question_count,
                    "category_slug": category_slug,
                    # Whether the student took the engine's recommendation or overrode it. The
                    # difference is the only read on whether the recommendation is trusted.
                    "source": "category" if category_slug else "recommended",
                    "review_due_count": rationale.get("review_due_count"),
                },
            )
            return session_row
        except HTTPException:
            raise
        except EntitlementRequired as error:
            # 402, not 403: the caller is authenticated and permitted in principle — they have
            # reached a paid boundary. The distinction is what lets the interface show an upgrade
            # prompt rather than an access error.
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=error.as_detail()
            ) from error
        except Exception as error:
            logging.error(f"Error in SessionController.start_practice: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def current_diagnostic(self, *, user: User) -> dict[str, Any] | None:
        """
        Read the caller's diagnostic: the one in progress, or the most recent finished one.

        A read-only companion to ``start_diagnostic``. Both the diagnostic intro page and the
        dashboard need to know whether a student has one open, has finished one, or has never
        taken one — and asking that question must not create a session as a side effect, which is
        exactly what calling the start endpoint to find out would do.

        Args:
            user: The authenticated caller.

        Returns:
            dict[str, Any] | None: Session state, or None when the student has never started one.

        Raises:
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing SessionController.current_diagnostic")
            active = await self.CRUDSession.get_active_for_user(
                user_id=user.id, session_type=SessionType.DIAGNOSTIC
            )
            if active is not None:
                return await self.get_state(user=user, session_id=active.id)

            recent = [
                item
                for item in await self.CRUDSession.list_for_user(user_id=user.id, limit=20)
                if item.type == SessionType.DIAGNOSTIC
            ]
            if not recent:
                return None
            return await self.get_state(user=user, session_id=recent[0].id)
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in SessionController.current_diagnostic: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def get_state(self, *, user: User, session_id: uuid.UUID) -> dict[str, Any]:
        """
        Read a session the caller owns, with its questions in the protected shape.

        Returns every question's prompt and metadata so the client can render the whole
        assessment without a request per question, and returns no ideal answer, expected concept,
        common mistake or rubric for any of them. The payload is assembled field by field rather
        than splatted from the version row, so a rubric cannot be included by accident.

        Args:
            user: The authenticated caller.
            session_id: Session to read.

        Returns:
            dict[str, Any]: Session state, progress, and the ordered questions.

        Raises:
            HTTPException 404: Unknown session, or one the caller does not own.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing SessionController.get_state")
            session_row = await self._require_own_session(user=user, session_id=session_id)
            attempts = await self.CRUDAttempt.list_for_session(session_id=session_id)
            answered = {attempt.question_id: attempt for attempt in attempts}
            categories = {
                category.slug: category.name for category in await self.CRUDCategory.list_all()
            }

            slots = sorted(session_row.questions, key=lambda item: item.position)
            # Two queries for the whole composition rather than two per slot. A diagnostic has 24
            # slots and this endpoint is read on every question of the sitting, so the per-slot
            # form made the cost of showing a session scale with its length for no reason.
            question_map = await self.CRUDQuestion.map_by_ids(
                question_ids=[slot.question_id for slot in slots]
            )
            version_map = await self.CRUDQuestionVersion.map_by_ids(
                version_ids=[slot.question_version_id for slot in slots]
            )

            questions = []
            for slot in slots:
                question = question_map.get(slot.question_id)
                version = version_map.get(slot.question_version_id)
                if question is None or version is None:
                    logging.error(f"Session {session_id} references missing question content")
                    continue

                attempt = answered.get(slot.question_id)
                questions.append(
                    {
                        "position": slot.position,
                        "id": question.id,
                        "question_version_id": version.id,
                        "category_slug": question.category_slug,
                        "category_name": categories.get(
                            question.category_slug, question.category_slug
                        ),
                        "subcategory": question.subcategory,
                        "difficulty": question.difficulty,
                        "prompt": version.prompt,
                        "attempt_id": attempt.id if attempt else None,
                        "grading_status": attempt.grading_status if attempt else None,
                    }
                )

            return {
                "id": session_row.id,
                "type": session_row.type,
                "status": session_row.status,
                "question_count": session_row.question_count,
                "answered_count": len(attempts),
                "started_at": session_row.started_at,
                "finished_at": session_row.finished_at,
                # The explanation written at selection time. Read from storage rather than
                # recomputed, so it still describes the state that actually produced this set.
                "selection_rationale": dict(session_row.selection_rationale or {}),
                "questions": questions,
            }
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in SessionController.get_state: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def complete(self, *, user: User, session_id: uuid.UUID) -> Session:
        """
        Mark a session finished once every question has been answered.

        Requires a complete set of answers rather than accepting a partial submission. A
        diagnostic scored on 11 of 24 questions would report readiness for categories the student
        never attempted, which is worse than no result at all.

        Completing does not require grading to have finished. Grading is asynchronous and can take
        longer than a student is willing to wait on a spinner; the results endpoint reports
        grading progress instead.

        Args:
            user: The authenticated caller.
            session_id: Session to complete.

        Returns:
            Session: The completed session.

        Raises:
            HTTPException 404: Unknown session, or one the caller does not own.
            HTTPException 409: Not every question has been answered.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing SessionController.complete")
            session_row = await self._require_own_session(user=user, session_id=session_id)
            if session_row.status != SessionStatus.IN_PROGRESS:
                # Already finished. Returning it rather than erroring makes a duplicate "finish"
                # click harmless, which is the same reasoning as duplicate answer submission.
                logging.info(f"Session {session_id} is already {session_row.status}")
                return session_row

            attempts = await self.CRUDAttempt.list_for_session(session_id=session_id)
            if len(attempts) < session_row.question_count:
                logging.warning(
                    f"Refused to complete session {session_id}: "
                    f"{len(attempts)}/{session_row.question_count} answered"
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        f"Answer all {session_row.question_count} questions before finishing. "
                        f"{len(attempts)} answered so far."
                    ),
                )

            completed = await self.CRUDSession.finish(
                session_id=session_id, status=SessionStatus.COMPLETED
            )
            logging.info(f"Completed session {session_id} for user {user.id}")
            track(
                event=AnalyticsEvent.DIAGNOSTIC_COMPLETED
                if session_row.type == SessionType.DIAGNOSTIC
                else AnalyticsEvent.PRACTICE_COMPLETED,
                user_id=user.id,
                properties={
                    "session_id": session_id,
                    "session_type": session_row.type,
                    "question_count": session_row.question_count,
                },
            )
            return completed or session_row
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in SessionController.complete: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def results(self, *, user: User, session_id: uuid.UUID) -> dict[str, Any]:
        """
        Assemble the results of a completed session.

        Reports grading progress first. When grading is still running the payload carries the
        counts and nothing else — no partial scores, no provisional mastery — because a readiness
        number computed from half the evidence is a wrong number, not an early one.

        Once every attempt has resolved, mastery is recomputed so the results page and the
        dashboard read the same stored score. That recomputation is idempotent, so re-fetching
        results does not compound anything.

        Args:
            user: The authenticated caller.
            session_id: Session to report on.

        Returns:
            dict[str, Any]: Grading progress, per-category results, strengths, weaknesses, and
            the recommended next action.

        Raises:
            HTTPException 404: Unknown session, or one the caller does not own.
            HTTPException 409: The session has not been completed.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing SessionController.results")
            session_row = await self._require_own_session(user=user, session_id=session_id)
            if session_row.status == SessionStatus.IN_PROGRESS:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Finish the session before viewing results",
                )

            attempts = await self.CRUDAttempt.list_for_session(session_id=session_id)
            graded = [item for item in attempts if item.grading_status == GradingStatus.GRADED]
            failed = [item for item in attempts if item.grading_status == GradingStatus.FAILED]
            pending = len(attempts) - len(graded) - len(failed)

            progress = {
                "total": session_row.question_count,
                "answered": len(attempts),
                "graded": len(graded),
                "failed": len(failed),
                "pending": pending,
                # Failures are terminal, so results are shown once nothing is still moving.
                # Waiting for a perfect run would strand a student behind one bad model call.
                "grading_complete": pending == 0,
            }
            base = {
                "session_id": session_row.id,
                "status": session_row.status,
                "finished_at": session_row.finished_at,
                "progress": progress,
            }
            if not progress["grading_complete"]:
                logging.info(f"Session {session_id} results requested while grading is in flight")
                return {**base, "categories": [], "strengths": [], "weaknesses": []}

            # Recomputed here rather than left to the nightly job, so a student sees their result
            # immediately and the dashboard agrees with it.
            await self.MasteryService.recalculate_for_user(user_id=user.id)
            payload = {**base, **await self._category_results(user=user, graded=graded)}
            # Recorded only once grading has resolved. The client polls this endpoint while
            # grading runs, and counting those polls would make the results page look read many
            # times more often than it was.
            track(
                event=AnalyticsEvent.RESULTS_VIEWED,
                user_id=user.id,
                properties={
                    "session_id": session_row.id,
                    "session_type": session_row.type,
                    "graded_count": len(graded),
                    "failed_count": len(failed),
                    "measured_categories": len(payload.get("categories", [])),
                },
            )
            return payload
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in SessionController.results: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def _category_results(self, *, user: User, graded: list[Attempt]) -> dict[str, Any]:
        """
        Build the per-category breakdown, strengths, weaknesses and next action.

        The headline number per category is the stored mastery score, not a mean of this
        session's three answers, so the results page and the dashboard can never disagree about
        how ready a student is. This session's scores are reported alongside it as the evidence
        behind that number.

        Args:
            user: The authenticated caller.
            graded: The session's graded attempts.

        Returns:
            dict[str, Any]: Categories, strengths, weaknesses, and the recommendation.
        """
        categories = await self.CRUDCategory.list_all()
        mastery = {
            score.category_slug: score
            for score in await self.CRUDSkillScore.list_for_user(user_id=user.id)
        }

        # One query for every question in the sitting rather than one per attempt; a diagnostic
        # has 24 of them, and all this loop needs from each is its category.
        question_map = await self.CRUDQuestion.map_by_ids(
            question_ids=[attempt.question_id for attempt in graded]
        )

        session_scores: dict[str, list[int]] = {}
        missed_concepts: dict[str, list[str]] = {}
        for attempt in graded:
            question = question_map.get(attempt.question_id)
            if question is None or attempt.score is None:
                continue
            session_scores.setdefault(question.category_slug, []).append(attempt.score)
            missed_concepts.setdefault(question.category_slug, []).extend(
                attempt.concepts_missed or []
            )

        rows: list[dict[str, Any]] = []
        for category in categories:
            scores = session_scores.get(category.slug, [])
            if not scores:
                continue
            stored = mastery.get(category.slug)
            rows.append(
                {
                    "slug": category.slug,
                    "name": category.name,
                    "score": stored.score if stored else round(sum(scores) / len(scores)),
                    "previous_score": stored.previous_score if stored else None,
                    "evidence_count": stored.evidence_count if stored else len(scores),
                    "session_scores": scores,
                    "answered": len(scores),
                    "missed_concepts": sorted(set(missed_concepts.get(category.slug, []))),
                }
            )

        ranked = sorted(rows, key=lambda row: row["score"])
        weaknesses = [row["slug"] for row in ranked if row["score"] <= WEAKNESS_THRESHOLD][:3]
        strengths = [row["slug"] for row in reversed(ranked) if row["score"] >= STRENGTH_THRESHOLD][
            :3
        ]

        return {
            "categories": rows,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "recommendation": self._recommendation(ranked),
        }

    @staticmethod
    def _recommendation(ranked: list[dict[str, Any]]) -> dict[str, Any] | None:
        """
        Build the single next action the results page should push.

        One recommendation, not a list. The results page exists to answer "what do I do now", and
        offering five equally weighted options is how a student closes the tab without doing any
        of them.

        Args:
            ranked: Category rows, weakest first.

        Returns:
            dict[str, Any] | None: The recommendation, or None when there is nothing to report.
        """
        if not ranked:
            return None

        weakest = ranked[0]
        missed = len(weakest["missed_concepts"])
        reason = f"{weakest['name']} is your weakest category at {weakest['score']}."
        if missed:
            reason += f" You missed {missed} expected concept{'s' if missed != 1 else ''} there."

        return {
            "action": "practise_category",
            "category_slug": weakest["slug"],
            "category_name": weakest["name"],
            "reason": reason,
        }

    async def _require_own_session(self, *, user: User, session_id: uuid.UUID) -> Session:
        """
        Load a session with its questions, or fail with 404.

        Another user's session is answered with 404 rather than 403, so session IDs cannot be
        probed for existence.

        Args:
            user: The authenticated caller.
            session_id: Session to load.

        Returns:
            Session: The session with its questions loaded.

        Raises:
            HTTPException 404: Unknown session, or one the caller does not own.
        """
        session_row = await self.CRUDSession.get_with_questions(session_id=session_id)
        if session_row is None or session_row.user_id != user.id:
            logging.warning(
                f"User {user.id} requested session {session_id} they do not own "
                f"or that does not exist"
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
        return session_row
