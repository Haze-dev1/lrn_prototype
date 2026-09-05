"""Answer submission and grade retrieval.

The ordering in ``submit`` is the most important thing in this file, and it is deliberate:
validate ownership, persist the answer, and only then grade. Grading is the step that can fail —
a provider outage, a timeout, a malformed response — and by the time it runs the student's work
is already durable. Every failure after that point costs a delay, never an answer.
"""

import uuid
from typing import Any

from fastapi import HTTPException, status

from commons.locks import user_gate_lock
from core import logger
from core.constants.enums import GradingStatus, SessionStatus, SessionType
from core.cruds.attempt_crud import CRUDAttempt, CRUDGradeFlag
from core.cruds.category_crud import CRUDCategory
from core.cruds.question_crud import CRUDQuestion, CRUDQuestionVersion
from core.cruds.session_crud import CRUDSession
from core.models.attempt_model import Attempt
from core.models.user_model import User
from core.services.analytics.events import AnalyticsEvent
from core.services.analytics.service import track
from core.services.billing.entitlement_service import EntitlementRequired, EntitlementService

logging = logger(__name__)


class AttemptController:
    """Accepts answers and serves the grades produced from them."""

    def __init__(self) -> None:
        """Initialise the controller with the CRUD layers it coordinates."""
        self.CRUDAttempt = CRUDAttempt()
        self.CRUDGradeFlag = CRUDGradeFlag()
        self.CRUDSession = CRUDSession()
        self.CRUDQuestion = CRUDQuestion()
        self.CRUDQuestionVersion = CRUDQuestionVersion()
        self.CRUDCategory = CRUDCategory()
        self.EntitlementService = EntitlementService()

    async def submit(
        self, *, user: User, session_id: uuid.UUID, payload: dict[str, Any]
    ) -> tuple[Attempt, bool]:
        """
        Persist a student's answer to one question of their own session.

        Repeated submission of the same question returns the original attempt rather than
        erroring or creating a second one. A double click, a client retry after a dropped
        response, and a refresh mid-submit are all the same event from the student's point of
        view, and none of them should produce two grades or two model calls. The unique
        constraint on (session_id, question_id) is the actual guarantee; this check makes the
        common case a clean 200 instead of a constraint violation.

        The question version is read from the session's stored composition, never from whatever
        is published now, so an answer is always graded against the rubric the student was shown.

        Args:
            user: The authenticated caller.
            session_id: Session the answer belongs to.
            payload: Question ID, answer text, and optional timing.

        Returns:
            tuple[Attempt, bool]: The attempt, and whether it already existed.

        Raises:
            HTTPException 400: The question ID is not a valid identifier.
            HTTPException 402: Today's free grading allowance is used up.
            HTTPException 404: Unknown session, a session the caller does not own, or a question
                that is not part of it.
            HTTPException 409: The session is no longer accepting answers.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing AttemptController.submit")
            try:
                question_id = uuid.UUID(str(payload["question_id"]))
            except (ValueError, AttributeError, KeyError) as error:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid question ID"
                ) from error

            session_row = await self.CRUDSession.get_with_questions(session_id=session_id)
            if session_row is None or session_row.user_id != user.id:
                # 404 rather than 403: a 403 would confirm the session exists, turning this
                # endpoint into an oracle for enumerating other users' sessions.
                logging.warning(
                    f"User {user.id} submitted to session {session_id} they do not own "
                    f"or that does not exist"
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
                )

            if session_row.status != SessionStatus.IN_PROGRESS:
                logging.warning(f"Rejected submission to {session_row.status} session {session_id}")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This session is no longer accepting answers",
                )

            slot = next(
                (item for item in session_row.questions if item.question_id == question_id), None
            )
            if slot is None:
                logging.warning(f"Question {question_id} is not part of session {session_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Question not found"
                )

            existing = await self.CRUDAttempt.get_for_session_question(
                session_id=session_id, question_id=question_id
            )
            if existing is not None:
                logging.info(f"Returning the existing attempt for question {question_id}")
                return existing, True

            # The check and the insert are held together under one per-user lock. Apart, they
            # are a check followed by a write, and concurrent submissions all read the same
            # pre-insert count and all pass — twenty answers were accepted against a limit of
            # fifteen, every one of them a paid model call.
            #
            # Inside it: after the duplicate check, so a client retry of an answer that is already
            # stored is never refused, and before the insert, so a refusal leaves no half-finished
            # attempt behind. The diagnostic is exempt inside the service: the free assessment is
            # graded in full or it measures nothing.
            async with user_gate_lock(user.id, name="grading"):
                await self.EntitlementService.require_grading(
                    user=user, session_type=session_row.type
                )

                attempt = await self.CRUDAttempt.create(
                    obj_in={
                        "session_id": session_id,
                        "user_id": user.id,
                        "question_id": question_id,
                        # Pinned from the session composition, not resolved at grading time.
                        "question_version_id": slot.question_version_id,
                        "answer": payload["answer"],
                        "time_taken_seconds": payload.get("time_taken_seconds"),
                        "grading_status": GradingStatus.PENDING,
                    }
                )
            logging.info(f"Persisted attempt {attempt.id} for question {question_id}")
            # The attempt, never the answer. This event exists to count submissions and time them
            # against grading, and the allowlist in the analytics service means the answer could
            # not travel here even if a future caller passed it.
            track(
                event=AnalyticsEvent.ANSWER_SUBMITTED,
                user_id=user.id,
                properties={
                    "attempt_id": attempt.id,
                    "session_id": session_id,
                    "session_type": session_row.type,
                    "question_id": question_id,
                },
            )
            return attempt, False
        except HTTPException:
            raise
        except EntitlementRequired as error:
            # 402 rather than 403: the caller is permitted in principle and has hit a paid
            # boundary, which is what lets the interface offer an upgrade instead of an error.
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=error.as_detail()
            ) from error
        except Exception as error:
            logging.error(f"Error in AttemptController.submit: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    @staticmethod
    def _labels_for(*, version: Any, keys: set[str]) -> dict[str, str]:
        """
        Map the concept and mistake keys in one grade to their readable labels.

        Restricted to the keys supplied, never the full declared set, so the response reveals
        exactly what the grade already names and nothing more.

        Args:
            version: The question version the attempt was graded against.
            keys: Keys present in this attempt's grade.

        Returns:
            dict[str, str]: Key to label, for the supplied keys only.
        """
        declared = [
            *(version.expected_concepts or []),
            *(version.common_mistakes or []),
        ]
        return {
            str(entry["key"]): str(entry.get("label") or entry["key"])
            for entry in declared
            if entry.get("key") and str(entry["key"]) in keys
        }

    async def get(self, *, user: User, attempt_id: uuid.UUID) -> dict[str, Any]:
        """
        Read one of the caller's own attempts, with its grade when it has one.

        This is the endpoint the interface polls while an answer is being graded, so it must be
        honest about the in-between states. An attempt that is pending, grading, or failed comes
        back with its status and nothing else — no score field to misread, no null the interface
        could render as a zero.

        Args:
            user: The authenticated caller.
            attempt_id: Attempt to read.

        Returns:
            dict[str, Any]: Attempt state, plus grade and question content once graded.

        Raises:
            HTTPException 404: No such attempt, or it belongs to another user.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing AttemptController.get")
            attempt = await self.CRUDAttempt.get_by_id(attempt_id=attempt_id)
            if attempt is None or attempt.user_id != user.id:
                logging.warning(
                    f"User {user.id} requested attempt {attempt_id} they do not own "
                    f"or that does not exist"
                )
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found"
                )

            state = {
                "id": attempt.id,
                "session_id": attempt.session_id,
                "question_id": attempt.question_id,
                "grading_status": attempt.grading_status,
                "submitted_at": attempt.submitted_at,
                "retry_count": attempt.retry_count,
            }
            if attempt.grading_status != GradingStatus.GRADED:
                return state

            # A diagnostic withholds every grade until the sitting is over. The interface already
            # declines to ask, but that is a client-side decision and this is the assessment's
            # integrity: a student who polled this endpoint between questions would learn their
            # score and read the reference answer while still being measured, which is exactly
            # the calibration the diagnostic exists to prevent. Practice is the opposite case —
            # learning from each answer is the point — so only an unfinished diagnostic is held
            # back. The session is read here, after the ungraded early return above, so polling
            # an answer that is still grading costs no extra query.
            session_row = await self.CRUDSession.get_by_id(session_id=attempt.session_id)
            if (
                session_row is not None
                and session_row.type == SessionType.DIAGNOSTIC
                and session_row.status == SessionStatus.IN_PROGRESS
            ):
                logging.info(
                    f"Withholding the grade for attempt {attempt_id}: its diagnostic is still "
                    f"in progress"
                )
                return state

            version = await self.CRUDQuestionVersion.get_by_id(
                version_id=attempt.question_version_id
            )
            question = await self.CRUDQuestion.get_by_id(question_id=attempt.question_id)
            if version is None or question is None:
                logging.error(f"Attempt {attempt_id} references missing question content")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found"
                )

            category = await self.CRUDCategory.get_by_slug(slug=question.category_slug)
            return {
                **state,
                # The student's own answer, returned to the student who wrote it. Needed weeks
                # later on the review page: a score without the answer it refers to cannot be
                # reviewed, only read.
                "answer": attempt.answer,
                "score": attempt.score,
                "band": attempt.band,
                "feedback": attempt.feedback,
                "concepts_hit": attempt.concepts_hit or [],
                "concepts_missed": attempt.concepts_missed or [],
                "mistake_flags": attempt.mistake_flags or [],
                "graded_at": attempt.graded_at,
                # The version the attempt was graded against, so review always shows the prompt
                # and reference answer the student actually saw — not a later revision.
                "question_prompt": version.prompt,
                "ideal_answer": version.ideal_answer,
                # Readable names for the keys that appear in *this* grade, and only those.
                # Returning the full declared list would hand over the question's complete answer
                # key — every concept and every anticipated mistake, including the ones the
                # student never triggered. That matters more than it looks: spaced repetition
                # brings missed questions back, so a student could memorise the checklist instead
                # of learning the material.
                "concept_labels": self._labels_for(
                    version=version,
                    keys={
                        *(attempt.concepts_hit or []),
                        *(attempt.concepts_missed or []),
                        *(attempt.mistake_flags or []),
                    },
                ),
                "category_slug": question.category_slug,
                "category_name": category.name if category else question.category_slug,
                # So the grade panel can show a flag as already raised rather than offering the
                # control again. A flag is a statement, not a vote.
                "flagged": await self.CRUDGradeFlag.get_for_attempt(
                    attempt_id=attempt_id, user_id=user.id
                )
                is not None,
            }
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AttemptController.get: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error
