"""Database access for the question bank and its versioned grading content."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from core import logger
from core.constants.enums import QuestionStatus, QuestionVersionStatus
from core.database.database import session
from core.models.question_model import Question, QuestionVersion

logging = logger(__name__)


class CRUDQuestion:
    """Database access layer for question identity and taxonomy."""

    async def create(self, *, obj_in: dict[str, Any]) -> Question:
        """
        Insert a question record.

        Args:
            obj_in: Question fields including category, difficulty and status.

        Returns:
            Question: The created question.

        Raises:
            Exception: If the insert fails.
        """
        try:
            logging.info("Executing CRUDQuestion.create")
            question = Question(**obj_in)
            async with session() as db:
                db.add(question)
                await db.flush()
                await db.refresh(question)
            return question
        except Exception as error:
            logging.error(f"Error in CRUDQuestion.create: {error}")
            raise error

    async def get_by_id(self, *, question_id: uuid.UUID) -> Question | None:
        """
        Read a question by primary key.

        Args:
            question_id: Question ID.

        Returns:
            Question | None: The question if found, otherwise None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDQuestion.get_by_id")
            async with session() as db:
                return await db.get(Question, question_id)
        except Exception as error:
            logging.error(f"Error in CRUDQuestion.get_by_id: {error}")
            raise error

    async def map_by_ids(self, *, question_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, Question]:
        """
        Read many questions by primary key in one round trip.

        Exists because the callers that need questions almost always need a whole set of them —
        a session's composition, a page of review — and fetching those one at a time made the
        request cost scale with the number of questions rather than staying flat. Returns a
        mapping so the caller keeps its own ordering, which is usually the stored composition
        order rather than anything the database would produce.

        Args:
            question_ids: Question IDs to read; duplicates and unknown IDs are tolerated.

        Returns:
            dict[uuid.UUID, Question]: Found questions by ID. Missing IDs are simply absent.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDQuestion.map_by_ids")
            unique = list(dict.fromkeys(question_ids))
            if not unique:
                return {}
            async with session() as db:
                result = await db.execute(select(Question).where(Question.id.in_(unique)))
                return {question.id: question for question in result.scalars().all()}
        except Exception as error:
            logging.error(f"Error in CRUDQuestion.map_by_ids: {error}")
            raise error

    async def list_selectable(
        self,
        *,
        category_slug: str | None = None,
        difficulty: int | None = None,
        exclude_question_ids: list[uuid.UUID] | None = None,
        limit: int = 50,
    ) -> list[Question]:
        """
        Read active questions eligible for inclusion in a session.

        Only ACTIVE questions are returned, and only those that already have a published version:
        a question with no published rubric cannot be graded, so offering it would guarantee a
        failed grade. Matches the partial index on (category_slug, difficulty).

        Args:
            category_slug: Restrict to one category when given.
            difficulty: Restrict to one difficulty level when given.
            exclude_question_ids: Questions to skip, typically ones the student has just seen.
            limit: Maximum rows to return.

        Returns:
            list[Question]: Matching active, gradeable questions.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDQuestion.list_selectable")
            published = (
                select(QuestionVersion.question_id)
                .where(QuestionVersion.status == QuestionVersionStatus.PUBLISHED)
                .scalar_subquery()
            )
            statement = (
                select(Question)
                .where(Question.status == QuestionStatus.ACTIVE)
                .where(Question.id.in_(published))
            )
            if category_slug is not None:
                statement = statement.where(Question.category_slug == category_slug)
            if difficulty is not None:
                statement = statement.where(Question.difficulty == difficulty)
            if exclude_question_ids:
                statement = statement.where(Question.id.notin_(exclude_question_ids))

            async with session() as db:
                result = await db.execute(
                    statement.order_by(Question.difficulty, Question.id).limit(limit)
                )
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDQuestion.list_selectable: {error}")
            raise error

    async def count_selectable_by_category(self) -> dict[str, int]:
        """
        Count gradeable active questions per category.

        Used to check the bank can actually satisfy a session's composition before one is started,
        rather than discovering a shortfall partway through building it.

        Returns:
            dict[str, int]: Category slug mapped to its count of selectable questions.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDQuestion.count_selectable_by_category")
            published = (
                select(QuestionVersion.question_id)
                .where(QuestionVersion.status == QuestionVersionStatus.PUBLISHED)
                .scalar_subquery()
            )
            async with session() as db:
                result = await db.execute(
                    select(Question.category_slug, func.count())
                    .where(Question.status == QuestionStatus.ACTIVE)
                    .where(Question.id.in_(published))
                    .group_by(Question.category_slug)
                )
                return {slug: count for slug, count in result.all()}
        except Exception as error:
            logging.error(f"Error in CRUDQuestion.count_selectable_by_category: {error}")
            raise error

    async def get_by_source_key(self, *, source_key: str) -> Question | None:
        """
        Read a question by its authored content key.

        Args:
            source_key: Stable key assigned by the content file.

        Returns:
            Question | None: The question if one claims that key, otherwise None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDQuestion.get_by_source_key")
            async with session() as db:
                result = await db.execute(select(Question).where(Question.source_key == source_key))
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDQuestion.get_by_source_key: {error}")
            raise error

    async def get_with_versions(self, *, question_id: uuid.UUID) -> Question | None:
        """
        Read a question together with its full version history.

        Versions are eager-loaded in the same round trip: the admin detail view always renders
        the history, so deferring it would only guarantee a second query.

        Args:
            question_id: Question ID.

        Returns:
            Question | None: The question with ``versions`` populated, or None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDQuestion.get_with_versions")
            async with session() as db:
                result = await db.execute(
                    select(Question)
                    .where(Question.id == question_id)
                    .options(selectinload(Question.versions))
                )
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDQuestion.get_with_versions: {error}")
            raise error

    async def list_for_admin(
        self,
        *,
        category_slug: str | None = None,
        status: str | None = None,
        difficulty: int | None = None,
        search: str | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[Question]:
        """
        Read a filtered page of questions with their versions, for content management.

        Paginated by keyset on ``created_at`` rather than by offset. Question IDs are UUIDv7, so
        creation order and key order agree, and a keyset page stays correct while an author is
        adding questions — an offset page would silently repeat or skip rows as the bank grows
        underneath the reader.

        Args:
            category_slug: Restrict to one category.
            status: Restrict to one lifecycle state.
            difficulty: Restrict to one difficulty level.
            search: Case-insensitive match against subcategory, source key, or version prompt.
            before: Return questions created strictly before this timestamp.
            limit: Maximum rows to return.

        Returns:
            list[Question]: Matching questions, newest first, with versions loaded.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDQuestion.list_for_admin")
            statement = select(Question).options(selectinload(Question.versions))

            if category_slug is not None:
                statement = statement.where(Question.category_slug == category_slug)
            if status is not None:
                statement = statement.where(Question.status == status)
            if difficulty is not None:
                statement = statement.where(Question.difficulty == difficulty)
            if before is not None:
                statement = statement.where(Question.created_at < before)
            if search:
                pattern = f"%{search.strip()}%"
                prompt_match = (
                    select(QuestionVersion.question_id)
                    .where(QuestionVersion.prompt.ilike(pattern))
                    .scalar_subquery()
                )
                statement = statement.where(
                    or_(
                        Question.subcategory.ilike(pattern),
                        Question.source_key.ilike(pattern),
                        Question.id.in_(prompt_match),
                    )
                )

            async with session() as db:
                result = await db.execute(
                    statement.order_by(Question.created_at.desc(), Question.id.desc()).limit(limit)
                )
                return list(result.scalars().unique().all())
        except Exception as error:
            logging.error(f"Error in CRUDQuestion.list_for_admin: {error}")
            raise error

    async def count_by_status(self) -> dict[str, int]:
        """
        Count questions grouped by lifecycle state.

        Returns:
            dict[str, int]: Status mapped to its question count.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDQuestion.count_by_status")
            async with session() as db:
                result = await db.execute(
                    select(Question.status, func.count()).group_by(Question.status)
                )
                return {status: count for status, count in result.all()}
        except Exception as error:
            logging.error(f"Error in CRUDQuestion.count_by_status: {error}")
            raise error

    async def update(self, *, question_id: uuid.UUID, obj_in: dict[str, Any]) -> Question | None:
        """
        Update a question's identity or taxonomy fields.

        Args:
            question_id: Question ID.
            obj_in: Fields to change.

        Returns:
            Question | None: The updated question, or None when it does not exist.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDQuestion.update")
            async with session() as db:
                question = await db.get(Question, question_id)
                if question is None:
                    logging.warning(f"No question found with id: {question_id}")
                    return None
                for field, value in obj_in.items():
                    setattr(question, field, value)
                await db.flush()
                await db.refresh(question)
            return question
        except Exception as error:
            logging.error(f"Error in CRUDQuestion.update: {error}")
            raise error


class CRUDQuestionVersion:
    """Database access layer for versioned question content and rubrics."""

    async def create(self, *, obj_in: dict[str, Any]) -> QuestionVersion:
        """
        Insert a question version.

        The version number is assigned here rather than by the caller, so two concurrent admin
        edits cannot both claim the same version — the unique constraint on
        (question_id, version) rejects the loser.

        Args:
            obj_in: Version fields; ``version`` is derived when absent.

        Returns:
            QuestionVersion: The created version.

        Raises:
            Exception: If the insert fails.
        """
        try:
            logging.info("Executing CRUDQuestionVersion.create")
            data = dict(obj_in)
            async with session() as db:
                if "version" not in data:
                    highest = await db.execute(
                        select(func.coalesce(func.max(QuestionVersion.version), 0)).where(
                            QuestionVersion.question_id == data["question_id"]
                        )
                    )
                    data["version"] = highest.scalar_one() + 1
                version = QuestionVersion(**data)
                db.add(version)
                await db.flush()
                await db.refresh(version)
            return version
        except Exception as error:
            logging.error(f"Error in CRUDQuestionVersion.create: {error}")
            raise error

    async def get_by_id(self, *, version_id: uuid.UUID) -> QuestionVersion | None:
        """
        Read a question version by primary key.

        Args:
            version_id: Question version ID.

        Returns:
            QuestionVersion | None: The version if found, otherwise None.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDQuestionVersion.get_by_id")
            async with session() as db:
                return await db.get(QuestionVersion, version_id)
        except Exception as error:
            logging.error(f"Error in CRUDQuestionVersion.get_by_id: {error}")
            raise error

    async def map_by_ids(
        self, *, version_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, QuestionVersion]:
        """
        Read many question versions by primary key in one round trip.

        The batch counterpart to ``get_by_id``, for the same reason: a session pins one version
        per question, so anything rendering a session needs as many versions as it has questions.

        Args:
            version_ids: Version IDs to read; duplicates and unknown IDs are tolerated.

        Returns:
            dict[uuid.UUID, QuestionVersion]: Found versions by ID. Missing IDs are simply absent.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDQuestionVersion.map_by_ids")
            unique = list(dict.fromkeys(version_ids))
            if not unique:
                return {}
            async with session() as db:
                result = await db.execute(
                    select(QuestionVersion).where(QuestionVersion.id.in_(unique))
                )
                return {version.id: version for version in result.scalars().all()}
        except Exception as error:
            logging.error(f"Error in CRUDQuestionVersion.map_by_ids: {error}")
            raise error

    async def get_published(self, *, question_id: uuid.UUID) -> QuestionVersion | None:
        """
        Read the currently published version of a question.

        At most one can exist, enforced by a partial unique index, so this is the single answer to
        "which rubric grades this question right now".

        Args:
            question_id: Question ID.

        Returns:
            QuestionVersion | None: The published version, or None when none is published.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDQuestionVersion.get_published")
            async with session() as db:
                result = await db.execute(
                    select(QuestionVersion)
                    .where(QuestionVersion.question_id == question_id)
                    .where(QuestionVersion.status == QuestionVersionStatus.PUBLISHED)
                )
                return result.scalar_one_or_none()
        except Exception as error:
            logging.error(f"Error in CRUDQuestionVersion.get_published: {error}")
            raise error

    async def list_for_question(self, *, question_id: uuid.UUID) -> list[QuestionVersion]:
        """
        Read a question's full version history, newest first.

        Args:
            question_id: Question ID.

        Returns:
            list[QuestionVersion]: Versions ordered from newest to oldest.

        Raises:
            Exception: If the database read fails.
        """
        try:
            logging.info("Executing CRUDQuestionVersion.list_for_question")
            async with session() as db:
                result = await db.execute(
                    select(QuestionVersion)
                    .where(QuestionVersion.question_id == question_id)
                    .order_by(QuestionVersion.version.desc())
                )
                return list(result.scalars().all())
        except Exception as error:
            logging.error(f"Error in CRUDQuestionVersion.list_for_question: {error}")
            raise error

    async def update_draft(
        self, *, version_id: uuid.UUID, obj_in: dict[str, Any]
    ) -> QuestionVersion | None:
        """
        Edit a draft version in place.

        Only DRAFT rows are writable. The immutability that matters is of versions that have
        graded something, and a draft never can: sessions are composed exclusively from published
        versions, so no attempt can point at a draft. Freezing drafts as well would force an
        author to burn a version number on every typo, and would bury real rubric history under
        editing noise.

        Args:
            version_id: Version to edit.
            obj_in: Content fields to change.

        Returns:
            QuestionVersion | None: The updated draft, or None when it does not exist.

        Raises:
            ValueError: If the version is published or superseded.
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDQuestionVersion.update_draft")
            async with session() as db:
                version = await db.get(QuestionVersion, version_id)
                if version is None:
                    logging.warning(f"No question version found with id: {version_id}")
                    return None
                if version.status != QuestionVersionStatus.DRAFT:
                    logging.warning(
                        f"Refused in-place edit of {version.status} version {version_id}"
                    )
                    raise ValueError("Only draft versions can be edited in place")
                for field, value in obj_in.items():
                    setattr(version, field, value)
                await db.flush()
                await db.refresh(version)
            return version
        except ValueError:
            raise
        except Exception as error:
            logging.error(f"Error in CRUDQuestionVersion.update_draft: {error}")
            raise error

    async def publish(self, *, version_id: uuid.UUID) -> QuestionVersion | None:
        """
        Publish a version, superseding whichever version was published before it.

        Both writes happen in one transaction. If they did not, the partial unique index would
        reject the new publish while the old one still held the slot, and a crash between them
        could leave a question with no published rubric at all.

        Args:
            version_id: Version to publish.

        Returns:
            QuestionVersion | None: The published version, or None when it does not exist.

        Raises:
            Exception: If the update fails.
        """
        try:
            logging.info("Executing CRUDQuestionVersion.publish")
            async with session() as db:
                version = await db.get(QuestionVersion, version_id)
                if version is None:
                    logging.warning(f"No question version found with id: {version_id}")
                    return None

                current = await db.execute(
                    select(QuestionVersion)
                    .where(QuestionVersion.question_id == version.question_id)
                    .where(QuestionVersion.status == QuestionVersionStatus.PUBLISHED)
                )
                for previous in current.scalars().all():
                    if previous.id != version.id:
                        previous.status = QuestionVersionStatus.SUPERSEDED
                await db.flush()

                version.status = QuestionVersionStatus.PUBLISHED
                await db.flush()
                await db.refresh(version)
            return version
        except Exception as error:
            logging.error(f"Error in CRUDQuestionVersion.publish: {error}")
            raise error
