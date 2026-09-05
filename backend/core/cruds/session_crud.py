"""Database access for sessions and their fixed question composition."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from core import logger
from core.constants.enums import GradingStatus, SessionStatus, SessionType
from core.database.database import session
from core.models.attempt_model import Attempt
from core.models.session_model import Session, SessionQuestion

logging = logger(__name__)


class CRUDSession:
    """Database access layer for diagnostic and practice sessions."""

    async def create_with_questions(
        self, *, obj_in: dict[str, Any], questions: list[dict[str, Any]]
    ) -> Session:
        """
        Insert a session together with its complete question composition.

        Both are written in one transaction so a session can never exist without the questions it
        is supposed to ask; a half-created session would strand the student on a blank screen with
        no way to resume or abandon it.

        Args:
            obj_in: Session fields such as user, type, and question count.
            questions: Ordered composition rows, each with position, question and version IDs.

        Returns:
            Session: The created session with its questions loaded.

        Raises:
            Exception: If the insert fails.
        """
        try:
            logging.info("Executing CRUDSession.create_with_questions")
            async with session() as db:
                new_session = Session(**obj_in)
                db.add(new_session)
                await db.flush()

                db.add_all(
                    [
                        SessionQuestion(session_id=new_session.id, **question)
                        for question in questions
                    ]
                )
                await db.flush()

                loaded = await db.execute(
                    select(Session)
                    .where(Session.id == new_session.id)
                    .options(selectinload(Session.questions))
                )
                return loaded.scalar_one()
        except Exception as error:
            logging.error(f"Error in CRUDSession.create_with_questions: {error}")
            raise error

    async def get_by_id(self, *, session_id: uuid.UUID) -> Session | None:
        """
        Read a session by primary key.

        Args:
            session_id: Session ID.

        Returns:
            Session | None: The session if found, otherwise None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSession.get_by_id")
            async with session() as db:
                return await db.get(Session, session_id)
        except Exception as error:
            logging.error(f"Error in CRUDSession.get_by_id: {error}")
            raise error

    async def get_with_questions(self, *, session_id: uuid.UUID) -> Session | None:
        """
        Read a session with its question composition eagerly loaded, in order.

        Eager loading avoids an N+1 query when rendering or resuming a session, and matters more
        for the 24-question diagnostic than for a 5-question practice set.

        Args:
            session_id: Session ID.

        Returns:
            Session | None: The session with questions loaded, or None when not found.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSession.get_with_questions")
            async with session() as db:
                result = await db.execute(
                    select(Session)
                    .where(Session.id == session_id)
                    .options(selectinload(Session.questions))
                )
                loaded = result.scalar_one_or_none()
            if loaded is not None:
                loaded.questions.sort(key=lambda item: item.position)
            return loaded
        except Exception as error:
            logging.error(f"Error in CRUDSession.get_with_questions: {error}")
            raise error

    async def get_active_for_user(
        self, *, user_id: uuid.UUID, session_type: str | None = None
    ) -> Session | None:
        """
        Read a user's in-progress session, so a returning student resumes rather than restarts.

        Matches the partial index on in-progress sessions.

        Args:
            user_id: Owning user ID.
            session_type: Restrict to one session type when given.

        Returns:
            Session | None: The most recent in-progress session, or None when there is none.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSession.get_active_for_user")
            statement = (
                select(Session)
                .where(Session.user_id == user_id)
                .where(Session.status == SessionStatus.IN_PROGRESS)
                .order_by(Session.started_at.desc())
                .limit(1)
            )
            if session_type is not None:
                statement = statement.where(Session.type == session_type)

            async with session() as db:
                result = await db.execute(statement)
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDSession.get_active_for_user: {error}")
            raise error

    async def list_for_user(
        self, *, user_id: uuid.UUID, limit: int = 20, before: datetime | None = None
    ) -> list[Session]:
        """
        Read a user's sessions newest-first, paginated by keyset.

        Pages by ``started_at`` rather than OFFSET so deep history stays as fast as the first
        page. Matches the (user_id, started_at) index.

        Args:
            user_id: Owning user ID.
            limit: Maximum rows to return.
            before: Return sessions started strictly before this timestamp.

        Returns:
            list[Session]: Sessions ordered newest first.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSession.list_for_user")
            statement = (
                select(Session)
                .where(Session.user_id == user_id)
                .order_by(Session.started_at.desc())
                .limit(limit)
            )
            if before is not None:
                statement = statement.where(Session.started_at < before)

            async with session() as db:
                result = await db.execute(statement)
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDSession.list_for_user: {error}")
            raise error

    async def count_by_type(self, *, user_id: uuid.UUID, session_type: str) -> int:
        """
        Count a user's sessions of one type.

        Used for the one-diagnostic free-tier rule, where every diagnostic counts however it
        ended. Practice has its own count — see ``count_practice_sets_answered`` — because
        starting a set abandons the previous one, so a raw session count would either charge a
        student for changing their mind or never charge them at all.

        Args:
            user_id: Owning user ID.
            session_type: Session type to count.

        Returns:
            int: Number of matching sessions.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSession.count_by_type")
            async with session() as db:
                result = await db.execute(
                    select(func.count())
                    .select_from(Session)
                    .where(Session.user_id == user_id)
                    .where(Session.type == session_type)
                )
                return int(result.scalar_one())
        except Exception as error:
            logging.error(f"Error in CRUDSession.count_by_type: {error}")
            raise error

    async def count_practice_sets_answered(self, *, user_id: uuid.UUID) -> int:
        """
        Count the practice sets a user has actually answered at least one question in.

        This, not a raw session count, is what the free practice allowance is measured against.
        Starting a set abandons any previous one, so counting sessions would either charge a
        student twice for reconsidering the set size, or — if abandoned sets were excluded —
        never charge them at all, because only one non-abandoned practice session ever exists.

        Answering is also the thing that costs anything: a composed set nobody touched consumed no
        grading. So a set counts from its first answer, and a set the student opened and left is
        free.

        Args:
            user_id: Owning user ID.

        Returns:
            int: Number of practice sets with at least one attempt.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSession.count_practice_sets_answered")
            async with session() as db:
                result = await db.execute(
                    select(func.count(func.distinct(Attempt.session_id)))
                    .select_from(Attempt)
                    .join(Session, Session.id == Attempt.session_id)
                    .where(Session.user_id == user_id)
                    .where(Session.type == SessionType.PRACTICE)
                )
                return int(result.scalar_one())
        except Exception as error:
            logging.error(f"Error in CRUDSession.count_practice_sets_answered: {error}")
            raise error

    async def list_diagnostics_awaiting_results_email(self, *, limit: int = 100) -> list[Session]:
        """
        Read finished diagnostics whose results email has not gone out.

        Selects only sessions where **every** attempt has finished grading. Sending on completion
        alone would mail a student a score computed from half their answers, which is a wrong
        number rather than an early one — the same rule the results page follows.

        A session whose attempts all failed grading is still returned: it has no pending work
        left, and the honest thing is to tell the student their diagnostic could not be graded
        rather than to leave them waiting for an email that will never come.

        Args:
            limit: Maximum sessions to return in one sweep.

        Returns:
            list[Session]: Diagnostics ready to be mailed, oldest first.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDSession.list_diagnostics_awaiting_results_email")
            unresolved = (
                select(Attempt.session_id)
                .where(Attempt.session_id == Session.id)
                .where(Attempt.grading_status.in_((GradingStatus.PENDING, GradingStatus.GRADING)))
            )
            async with session() as db:
                result = await db.execute(
                    select(Session)
                    .where(Session.type == SessionType.DIAGNOSTIC)
                    .where(Session.status == SessionStatus.COMPLETED)
                    .where(Session.results_email_sent_at.is_(None))
                    .where(~unresolved.exists())
                    .order_by(Session.finished_at.asc())
                    .limit(limit)
                )
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDSession.list_diagnostics_awaiting_results_email: {error}")
            raise error

    async def mark_results_email_sent(self, *, session_id: uuid.UUID) -> None:
        """
        Record that a diagnostic's results email was delivered.

        Written only after the provider accepted the message, so a failed send leaves the marker
        unset and the next sweep tries again. That ordering is the whole exactly-once guarantee:
        marking first would turn one provider outage into results emails that are never sent.

        Args:
            session_id: The diagnostic that was mailed.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDSession.mark_results_email_sent")
            async with session() as db:
                session_row = await db.get(Session, session_id)
                if session_row is not None:
                    session_row.results_email_sent_at = datetime.now(UTC)
                    await db.flush()
        except Exception as error:
            logging.error(f"Error in CRUDSession.mark_results_email_sent: {error}")
            raise error

    async def finish(self, *, session_id: uuid.UUID, status: str) -> Session | None:
        """
        Mark a session finished and stamp its completion time.

        The status and timestamp are set together because the database requires them to agree:
        an in-progress session must have no finish time, and a finished one must have it.

        Args:
            session_id: Session ID.
            status: Terminal status, either completed or abandoned.

        Returns:
            Session | None: The updated session, or None when not found.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDSession.finish")
            async with session() as db:
                target = await db.get(Session, session_id)
                if target is None:
                    logging.warning(f"No session found with id: {session_id}")
                    return None
                target.status = status
                target.finished_at = datetime.now(UTC)
                await db.flush()
                await db.refresh(target)
            return target
        except Exception as error:
            logging.error(f"Error in CRUDSession.finish: {error}")
            raise error
