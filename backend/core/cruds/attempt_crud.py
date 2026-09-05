"""Database access for attempts, grading audit events, and grade flags."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select, text

from core import logger
from core.constants.enums import (
    GradeFlagStatus,
    GradingStatus,
    SessionStatus,
    SessionType,
)
from core.database.database import session
from core.models.attempt_model import Attempt, GradeEvent, GradeFlag
from core.models.question_model import Question
from core.models.session_model import Session as SessionModel

logging = logger(__name__)


class CRUDAttempt:
    """Database access layer for student attempts."""

    async def create(self, *, obj_in: dict[str, Any]) -> Attempt:
        """
        Persist an attempt before any grading is attempted.

        The answer is stored first and separately from grading, so a provider failure can never
        destroy the student's work. The unique constraint on (session_id, question_id) makes a
        duplicate submit fail here rather than silently creating a second attempt.

        Args:
            obj_in: Attempt fields including session, user, question, version and answer.

        Returns:
            Attempt: The created attempt, in PENDING grading state.

        Raises:
            Exception: If the insert fails, including on duplicate submission.
        """
        try:
            logging.info("Executing CRUDAttempt.create")
            attempt = Attempt(**obj_in)
            async with session() as db:
                db.add(attempt)
                await db.flush()
                await db.refresh(attempt)
            return attempt
        except Exception as error:
            logging.error(f"Error in CRUDAttempt.create: {error}")
            raise error

    async def get_by_id(self, *, attempt_id: uuid.UUID) -> Attempt | None:
        """
        Read an attempt by primary key.

        Args:
            attempt_id: Attempt ID.

        Returns:
            Attempt | None: The attempt if found, otherwise None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDAttempt.get_by_id")
            async with session() as db:
                return await db.get(Attempt, attempt_id)
        except Exception as error:
            logging.error(f"Error in CRUDAttempt.get_by_id: {error}")
            raise error

    async def get_for_session_question(
        self, *, session_id: uuid.UUID, question_id: uuid.UUID
    ) -> Attempt | None:
        """
        Read the existing attempt for one question within a session.

        Lets a repeated submission return the original attempt instead of erroring, which is what
        makes a double-click or a client retry safe.

        Args:
            session_id: Session ID.
            question_id: Question ID.

        Returns:
            Attempt | None: The existing attempt, or None when the question is unanswered.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDAttempt.get_for_session_question")
            async with session() as db:
                result = await db.execute(
                    select(Attempt)
                    .where(Attempt.session_id == session_id)
                    .where(Attempt.question_id == question_id)
                )
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDAttempt.get_for_session_question: {error}")
            raise error

    async def list_for_user(
        self,
        *,
        user_id: uuid.UUID,
        category_slug: str | None = None,
        max_score: int | None = None,
        missed_concept: str | None = None,
        flagged_only: bool = False,
        graded_only: bool = True,
        exclude_unfinished_diagnostic: bool = False,
        since: datetime | None = None,
        limit: int = 20,
        before: datetime | None = None,
    ) -> list[Attempt]:
        """
        Read a user's attempts newest-first, with the review filters applied.

        Keyset paginated on ``submitted_at`` so deep review history costs the same as the first
        page. Matches the (user_id, submitted_at) index.

        Args:
            user_id: Owning user ID.
            category_slug: Restrict to one category when given.
            max_score: Return only attempts scoring at or below this value.
            missed_concept: Return only attempts whose grade recorded this concept as missed.
            flagged_only: Return only attempts the user has disputed.
            graded_only: Exclude attempts that have not finished grading.
            exclude_unfinished_diagnostic: Drop attempts belonging to a diagnostic the
                caller has not finished. Set by review, which is history; left off for the
                data export, which must return everything the account holds.
            since: Return attempts submitted at or after this time.
            limit: Maximum rows to return.
            before: Return attempts submitted strictly before this timestamp.

        Returns:
            list[Attempt]: Matching attempts, newest first.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDAttempt.list_for_user")
            statement = (
                select(Attempt)
                .where(Attempt.user_id == user_id)
                .order_by(Attempt.submitted_at.desc())
                .limit(limit)
            )
            if graded_only:
                statement = statement.where(Attempt.grading_status == GradingStatus.GRADED)
            # Review is history, and a diagnostic is not history until it is finished. Without
            # this a student could read their per-question scores here between questions — the
            # same calibration the results endpoint refuses with a 409 and the attempt endpoint
            # withholds, reached through a third door. Practice is deliberately not excluded:
            # its grades are revealed as they are earned, by design.
            if exclude_unfinished_diagnostic:
                unfinished_diagnostics = (
                    select(SessionModel.id)
                    .where(
                        SessionModel.user_id == user_id,
                        SessionModel.type == SessionType.DIAGNOSTIC,
                        SessionModel.status == SessionStatus.IN_PROGRESS,
                    )
                    .scalar_subquery()
                )
                statement = statement.where(Attempt.session_id.not_in(unfinished_diagnostics))
            if category_slug is not None:
                statement = statement.join(Question, Question.id == Attempt.question_id).where(
                    Question.category_slug == category_slug
                )
            if max_score is not None:
                statement = statement.where(Attempt.score <= max_score)
            if missed_concept is not None:
                # Containment against the JSONB array, so the GIN-indexable operator is used
                # rather than unnesting every attempt's concept list in Python.
                statement = statement.where(Attempt.concepts_missed.contains([missed_concept]))
            if flagged_only:
                flagged = (
                    select(GradeFlag.attempt_id)
                    .where(GradeFlag.user_id == user_id)
                    .scalar_subquery()
                )
                statement = statement.where(Attempt.id.in_(flagged))
            if since is not None:
                statement = statement.where(Attempt.submitted_at >= since)
            if before is not None:
                statement = statement.where(Attempt.submitted_at < before)

            async with session() as db:
                result = await db.execute(statement)
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDAttempt.list_for_user: {error}")
            raise error

    async def list_for_session(self, *, session_id: uuid.UUID) -> list[Attempt]:
        """
        Read every attempt belonging to a session.

        Args:
            session_id: Session ID.

        Returns:
            list[Attempt]: Attempts ordered by submission time.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDAttempt.list_for_session")
            async with session() as db:
                result = await db.execute(
                    select(Attempt)
                    .where(Attempt.session_id == session_id)
                    .order_by(Attempt.submitted_at)
                )
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDAttempt.list_for_session: {error}")
            raise error

    async def list_due_for_retry(
        self, *, older_than_seconds: int, limit: int = 50
    ) -> list[Attempt]:
        """
        Read attempts whose grading has not resolved, for the retry sweep.

        The age filter avoids picking up an attempt that is still being graded in the request that
        created it, which would cause two concurrent grading calls for one answer. Matches the
        partial index over unresolved grading states.

        Args:
            older_than_seconds: Minimum age before an unresolved attempt is retried.
            limit: Maximum rows to return in one sweep.

        Returns:
            list[Attempt]: Unresolved attempts, oldest first.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDAttempt.list_due_for_retry")
            cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
            async with session() as db:
                result = await db.execute(
                    select(Attempt)
                    .where(
                        Attempt.grading_status.in_(
                            [GradingStatus.PENDING, GradingStatus.GRADING, GradingStatus.FAILED]
                        )
                    )
                    .where(Attempt.submitted_at < cutoff)
                    .order_by(Attempt.submitted_at)
                    .limit(limit)
                )
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDAttempt.list_due_for_retry: {error}")
            raise error

    async def set_grade_result(
        self, *, attempt_id: uuid.UUID, result: dict[str, Any]
    ) -> Attempt | None:
        """
        Write a successful grade onto an attempt and mark it graded.

        Sets the status, score, band and graded timestamp together, because the database rejects
        any combination where a graded attempt lacks its result.

        Args:
            attempt_id: Attempt ID.
            result: Validated grade fields — score, band, feedback, concepts and mistake flags.

        Returns:
            Attempt | None: The updated attempt, or None when it does not exist.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDAttempt.set_grade_result")
            async with session() as db:
                attempt = await db.get(Attempt, attempt_id)
                if attempt is None:
                    logging.warning(f"No attempt found with id: {attempt_id}")
                    return None
                for field, value in result.items():
                    setattr(attempt, field, value)
                attempt.grading_status = GradingStatus.GRADED
                attempt.graded_at = datetime.now(UTC)
                await db.flush()
                await db.refresh(attempt)
            return attempt
        except Exception as error:
            logging.error(f"Error in CRUDAttempt.set_grade_result: {error}")
            raise error

    async def set_grading_status(
        self, *, attempt_id: uuid.UUID, status: str, increment_retry: bool = False
    ) -> Attempt | None:
        """
        Move an attempt to a non-graded grading state.

        Never writes a score. A failed grading must remain distinguishable from a genuinely poor
        answer, so the score stays null and the interface shows a retry state rather than a zero.

        Args:
            attempt_id: Attempt ID.
            status: Target status — pending, grading, or failed.
            increment_retry: Whether this transition counts as another grading attempt.

        Returns:
            Attempt | None: The updated attempt, or None when it does not exist.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDAttempt.set_grading_status")
            async with session() as db:
                attempt = await db.get(Attempt, attempt_id)
                if attempt is None:
                    logging.warning(f"No attempt found with id: {attempt_id}")
                    return None
                attempt.grading_status = status
                if increment_retry:
                    attempt.retry_count += 1
                await db.flush()
                await db.refresh(attempt)
            return attempt
        except Exception as error:
            logging.error(f"Error in CRUDAttempt.set_grading_status: {error}")
            raise error

    async def count_graded_since(self, *, user_id: uuid.UUID, since: datetime) -> int:
        """
        Count the answers a user has sent for grading since a point in time.

        Backs the free-tier daily grading limit, which must be enforced server-side because each
        graded answer costs a paid model call.

        Counts by **submission**, not by completed grading. Grading is asynchronous, so an
        attempt exists and has already been dispatched to the provider well before it has a
        ``graded_at``. Counting only finished grades leaves exactly that window open: answers
        submitted faster than they can be graded are invisible to the counter, and a burst walks
        straight past the cap — measured at 20 accepted against a limit of 15, and far worse with
        a real provider, where a call takes seconds rather than milliseconds. The spend is
        committed when the answer is accepted, so that is when it must be counted.

        Diagnostic answers are excluded, because the diagnostic is exempt from this limit rather
        than merely permitted to exceed it. Counting them would let a 24-question sitting consume
        a 15-answer allowance and refuse every practice answer for the rest of the day — to a
        student who has just been told to take that diagnostic, and who has not practised at all.
        The diagnostic is bounded by the one-diagnostic rule instead.

        Args:
            user_id: Owning user ID.
            since: Start of the counting window.

        Returns:
            int: Number of non-diagnostic answers submitted for grading in the window.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDAttempt.count_graded_since")
            async with session() as db:
                result = await db.execute(
                    select(func.count())
                    .select_from(Attempt)
                    .join(SessionModel, SessionModel.id == Attempt.session_id)
                    .where(Attempt.user_id == user_id)
                    .where(Attempt.submitted_at >= since)
                    .where(SessionModel.type != SessionType.DIAGNOSTIC)
                )
                return int(result.scalar_one())
        except Exception as error:
            logging.error(f"Error in CRUDAttempt.count_graded_since: {error}")
            raise error

    async def list_graded_for_mastery(
        self, *, user_id: uuid.UUID, since: datetime | None = None
    ) -> list[tuple[str, int, datetime]]:
        """
        Read a user's graded scores with their category and timestamp, for mastery calculation.

        Returns tuples rather than ORM objects because the mastery rollup only needs three
        columns per attempt and may process thousands of rows per user; hydrating full attempt
        objects, each carrying its answer text, would dominate the job's memory use.

        Args:
            user_id: Owning user ID.
            since: Ignore attempts graded before this time when given.

        Returns:
            list[tuple[str, int, datetime]]: (category_slug, score, graded_at) per graded attempt.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDAttempt.list_graded_for_mastery")
            statement = (
                select(Question.category_slug, Attempt.score, Attempt.graded_at)
                .join(Question, Question.id == Attempt.question_id)
                .where(Attempt.user_id == user_id)
                .where(Attempt.grading_status == GradingStatus.GRADED)
                .where(Attempt.score.is_not(None))
                .where(Attempt.graded_at.is_not(None))
                .order_by(Attempt.graded_at)
            )
            if since is not None:
                statement = statement.where(Attempt.graded_at >= since)

            async with session() as db:
                result = await db.execute(statement)
                return [(slug, int(score), graded_at) for slug, score, graded_at in result.all()]
        except Exception as error:
            logging.error(f"Error in CRUDAttempt.list_graded_for_mastery: {error}")
            raise error

    async def list_question_history(
        self, *, user_id: uuid.UUID
    ) -> list[tuple[uuid.UUID, int, int, datetime]]:
        """
        Read one row per question the user has ever been graded on.

        Practice selection needs three things about every question a student has seen: how many
        times they answered it, how they did most recently, and when. Fetching whole attempt rows
        to derive that would pull every answer's full text into memory to compute three numbers,
        so the aggregation happens in the database and only the numbers come back.

        Matches the (user_id, question_id, submitted_at) index.

        Args:
            user_id: Owning user ID.

        Returns:
            list[tuple[uuid.UUID, int, int, datetime]]: (question_id, attempt_count, latest_score,
            latest_graded_at) for every question with at least one graded attempt.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDAttempt.list_question_history")
            # DISTINCT ON takes the newest row per question in one pass; the count comes from a
            # window function over the same scan rather than a second grouped query.
            statement = text(
                """
                SELECT DISTINCT ON (question_id)
                       question_id,
                       COUNT(*) OVER (PARTITION BY question_id) AS attempt_count,
                       score,
                       graded_at
                FROM attempts
                WHERE user_id = :user_id
                  AND grading_status = 'graded'
                  AND score IS NOT NULL
                  AND graded_at IS NOT NULL
                ORDER BY question_id, graded_at DESC
                """
            )
            async with session() as db:
                result = await db.execute(statement, {"user_id": user_id})
                return [
                    (question_id, int(count), int(score), graded_at)
                    for question_id, count, score, graded_at in result.all()
                ]
        except Exception as error:
            logging.error(f"Error in CRUDAttempt.list_question_history: {error}")
            raise error

    async def list_user_ids_graded_since(self, *, since: datetime) -> list[uuid.UUID]:
        """
        Read the IDs of users with graded activity since a point in time.

        Lets the nightly rollup recompute only users whose evidence actually changed, so job cost
        tracks activity rather than total registrations.

        Args:
            since: Start of the activity window.

        Returns:
            list[uuid.UUID]: Distinct user IDs with graded attempts in the window.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDAttempt.list_user_ids_graded_since")
            async with session() as db:
                result = await db.execute(
                    select(Attempt.user_id)
                    .where(Attempt.grading_status == GradingStatus.GRADED)
                    .where(Attempt.graded_at >= since)
                    .distinct()
                )
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDAttempt.list_user_ids_graded_since: {error}")
            raise error


class CRUDGradeEvent:
    """Database access layer for the grading audit trail."""

    async def create(self, *, obj_in: dict[str, Any]) -> GradeEvent:
        """
        Append an audit record for one grading call.

        Written for failures as well as successes: a grading regression can only be attributed if
        the calls that went wrong were recorded too.

        Args:
            obj_in: Audit fields including provider, model, versions, usage and validation status.

        Returns:
            GradeEvent: The created audit record.

        Raises:
            Exception: If the insert fails.
        """
        try:
            logging.info("Executing CRUDGradeEvent.create")
            event = GradeEvent(**obj_in)
            async with session() as db:
                db.add(event)
                await db.flush()
                await db.refresh(event)
            return event
        except Exception as error:
            logging.error(f"Error in CRUDGradeEvent.create: {error}")
            raise error

    async def list_for_attempt(self, *, attempt_id: uuid.UUID) -> list[GradeEvent]:
        """
        Read the audit trail for one attempt, oldest first.

        Args:
            attempt_id: Attempt ID.

        Returns:
            list[GradeEvent]: Audit records in chronological order.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDGradeEvent.list_for_attempt")
            async with session() as db:
                result = await db.execute(
                    select(GradeEvent)
                    .where(GradeEvent.attempt_id == attempt_id)
                    .order_by(GradeEvent.created_at)
                )
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDGradeEvent.list_for_attempt: {error}")
            raise error


class CRUDGradeFlag:
    """Database access layer for disputed grades."""

    async def create(self, *, obj_in: dict[str, Any]) -> GradeFlag:
        """
        Record a student's dispute of a grade.

        Args:
            obj_in: Flag fields including attempt, user, and reason.

        Returns:
            GradeFlag: The created flag.

        Raises:
            Exception: If the insert fails, including when the user already flagged this attempt.
        """
        try:
            logging.info("Executing CRUDGradeFlag.create")
            flag = GradeFlag(**obj_in)
            async with session() as db:
                db.add(flag)
                await db.flush()
                await db.refresh(flag)
            return flag
        except Exception as error:
            logging.error(f"Error in CRUDGradeFlag.create: {error}")
            raise error

    async def get_for_attempt(
        self, *, attempt_id: uuid.UUID, user_id: uuid.UUID
    ) -> GradeFlag | None:
        """
        Read a user's flag on one attempt, if they have raised one.

        Args:
            attempt_id: Attempt ID.
            user_id: The user who may have flagged it.

        Returns:
            GradeFlag | None: The flag, or None when the user has not disputed this grade.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDGradeFlag.get_for_attempt")
            async with session() as db:
                result = await db.execute(
                    select(GradeFlag)
                    .where(GradeFlag.attempt_id == attempt_id)
                    .where(GradeFlag.user_id == user_id)
                )
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDGradeFlag.get_for_attempt: {error}")
            raise error

    async def list_attempt_ids_for_user(self, *, user_id: uuid.UUID) -> set[uuid.UUID]:
        """
        Read the IDs of every attempt a user has flagged.

        Returned as a set so a review page can mark flagged rows without one query per row.

        Args:
            user_id: Owning user ID.

        Returns:
            set[uuid.UUID]: Flagged attempt IDs.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDGradeFlag.list_attempt_ids_for_user")
            async with session() as db:
                result = await db.execute(
                    select(GradeFlag.attempt_id).where(GradeFlag.user_id == user_id)
                )
                return set(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDGradeFlag.list_attempt_ids_for_user: {error}")
            raise error

    async def list_open(self, *, limit: int = 50) -> list[GradeFlag]:
        """
        Read unresolved flags for the admin review queue, oldest first.

        Matches the partial index over open and reviewing flags.

        Args:
            limit: Maximum rows to return.

        Returns:
            list[GradeFlag]: Unresolved flags in age order.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDGradeFlag.list_open")
            async with session() as db:
                result = await db.execute(
                    select(GradeFlag)
                    .where(GradeFlag.status.in_([GradeFlagStatus.OPEN, GradeFlagStatus.REVIEWING]))
                    .order_by(GradeFlag.created_at)
                    .limit(limit)
                )
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDGradeFlag.list_open: {error}")
            raise error

    async def resolve(
        self, *, flag_id: uuid.UUID, status: str, reviewer_id: uuid.UUID, resolution: str
    ) -> GradeFlag | None:
        """
        Close a flag with an outcome and reviewer.

        Status and resolution timestamp are set together because the database requires a
        resolved or rejected flag to carry the time it was closed.

        Args:
            flag_id: Flag ID.
            status: Terminal status — resolved or rejected.
            reviewer_id: Admin user who reviewed it.
            resolution: Short explanation of the outcome.

        Returns:
            GradeFlag | None: The updated flag, or None when it does not exist.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDGradeFlag.resolve")
            async with session() as db:
                flag = await db.get(GradeFlag, flag_id)
                if flag is None:
                    logging.warning(f"No grade flag found with id: {flag_id}")
                    return None
                flag.status = status
                flag.reviewer_id = reviewer_id
                flag.resolution = resolution
                flag.resolved_at = datetime.now(UTC)
                await db.flush()
                await db.refresh(flag)
            return flag
        except Exception as error:
            logging.error(f"Error in CRUDGradeFlag.resolve: {error}")
            raise error
