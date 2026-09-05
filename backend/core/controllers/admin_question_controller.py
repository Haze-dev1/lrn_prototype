"""Administrative question bank management.

Owns the lifecycle rules the database cannot express. The schema guarantees that a *published*
version is complete and that only one exists per question; it cannot know that activating a
question with no published version would put an ungradeable item into the diagnostic pool, or
that a rubric can be improved but never rewritten. Those rules live here.

Every method takes the acting administrator explicitly. Authorisation is settled by the route's
dependency, but authorship is recorded here, so a version can always be traced to the person who
wrote it.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status

from core import logger
from core.constants.enums import QuestionStatus, QuestionVersionStatus
from core.cruds.category_crud import CRUDCategory
from core.cruds.question_crud import CRUDQuestion, CRUDQuestionVersion
from core.models.question_model import Question, QuestionVersion
from core.models.user_model import User
from core.services.questions.rubric_service import RubricValidator

logging = logger(__name__)

# A diagnostic asks three questions in each of the eight categories. Reporting readiness against
# the composition the product actually builds is the only number a content owner can act on.
DIAGNOSTIC_QUESTIONS_PER_CATEGORY = 3
MAX_ADMIN_PAGE_SIZE = 100


class AdminQuestionController:
    """Question and version management for content administrators."""

    def __init__(self) -> None:
        """Initialise the controller with the CRUD layers and services it coordinates."""
        self.CRUDQuestion = CRUDQuestion()
        self.CRUDQuestionVersion = CRUDQuestionVersion()
        self.CRUDCategory = CRUDCategory()
        self.RubricValidator = RubricValidator()

    # ----------------------------------------------------------------------------------
    # Reads
    # ----------------------------------------------------------------------------------

    async def list_questions(
        self,
        *,
        category_slug: str | None = None,
        question_status: str | None = None,
        difficulty: int | None = None,
        search: str | None = None,
        before: datetime | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """
        Read a filtered page of questions for the admin list view.

        Fetches one row beyond the requested page to decide whether a next cursor exists, which
        avoids a second COUNT query over a table that only grows.

        Args:
            category_slug: Restrict to one category.
            question_status: Restrict to one lifecycle state.
            difficulty: Restrict to one difficulty level.
            search: Free-text match on subcategory, source key, or prompt.
            before: Keyset cursor; return questions created before this timestamp.
            limit: Page size, capped server-side.

        Returns:
            dict[str, Any]: Page items and the cursor for the next page.

        Raises:
            HTTPException 400: An unknown category or lifecycle state was requested.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing AdminQuestionController.list_questions")
            if question_status is not None and question_status not in set(QuestionStatus):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown question status"
                )
            if category_slug is not None:
                await self._require_category(category_slug)

            page_size = max(1, min(limit, MAX_ADMIN_PAGE_SIZE))
            rows = await self.CRUDQuestion.list_for_admin(
                category_slug=category_slug,
                status=question_status,
                difficulty=difficulty,
                search=search,
                before=before,
                limit=page_size + 1,
            )

            has_more = len(rows) > page_size
            page = rows[:page_size]
            return {
                "items": [self._question_summary(question) for question in page],
                "next_cursor": page[-1].created_at if has_more and page else None,
            }
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AdminQuestionController.list_questions: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def get_question(self, *, question_id: uuid.UUID) -> dict[str, Any]:
        """
        Read one question with its full version history.

        Args:
            question_id: Question ID.

        Returns:
            dict[str, Any]: Question metadata and version summaries, newest first.

        Raises:
            HTTPException 404: No such question.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing AdminQuestionController.get_question")
            question = await self._require_question(question_id)
            payload = self._question_summary(question)
            payload["versions"] = [
                self._version_summary(version)
                for version in sorted(question.versions, key=lambda v: v.version, reverse=True)
            ]
            return payload
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AdminQuestionController.get_question: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def get_version(
        self, *, question_id: uuid.UUID, version_id: uuid.UUID
    ) -> QuestionVersion:
        """
        Read one version in full, including its grading content.

        The version is checked to belong to the question in the path rather than being looked up
        by ID alone, so a mistyped or stale question ID cannot silently return another question's
        rubric.

        Args:
            question_id: Question the version must belong to.
            version_id: Version ID.

        Returns:
            QuestionVersion: The version with all grading content.

        Raises:
            HTTPException 404: No such version, or it belongs to another question.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing AdminQuestionController.get_version")
            version = await self.CRUDQuestionVersion.get_by_id(version_id=version_id)
            if version is None or version.question_id != question_id:
                logging.warning(f"Version {version_id} not found on question {question_id}")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Question version not found"
                )
            return version
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AdminQuestionController.get_version: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def coverage(self) -> dict[str, Any]:
        """
        Report how much gradeable content each category holds.

        Answers the only question a content owner really has: can the bank compose a diagnostic,
        and where are the gaps? Counts only ACTIVE questions with a published version, because
        anything else cannot be served or graded.

        Returns:
            dict[str, Any]: Per-category counts, the total, and diagnostic readiness.

        Raises:
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing AdminQuestionController.coverage")
            categories = await self.CRUDCategory.list_all()
            selectable = await self.CRUDQuestion.count_selectable_by_category()
            by_status = await self.CRUDQuestion.count_by_status()

            rows = [
                {
                    "slug": category.slug,
                    "name": category.name,
                    "selectable": selectable.get(category.slug, 0),
                    "required": DIAGNOSTIC_QUESTIONS_PER_CATEGORY,
                    "shortfall": max(
                        0,
                        DIAGNOSTIC_QUESTIONS_PER_CATEGORY - selectable.get(category.slug, 0),
                    ),
                }
                for category in categories
            ]
            return {
                "categories": rows,
                "total_selectable": sum(row["selectable"] for row in rows),
                "diagnostic_ready": bool(rows) and all(row["shortfall"] == 0 for row in rows),
                "counts_by_status": {
                    state.value: by_status.get(state.value, 0) for state in QuestionStatus
                },
            }
        except Exception as error:
            logging.error(f"Error in AdminQuestionController.coverage: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    # ----------------------------------------------------------------------------------
    # Writes
    # ----------------------------------------------------------------------------------

    async def create_question(self, *, admin: User, payload: dict[str, Any]) -> dict[str, Any]:
        """
        Create a question, optionally with its first draft version.

        A question is created DRAFT regardless of what the caller asks for: it has no published
        rubric yet, so making it ACTIVE would advertise an ungradeable item to the selection
        engine.

        Args:
            admin: The acting administrator, recorded as the version author.
            payload: Taxonomy fields and an optional ``initial_version``.

        Returns:
            dict[str, Any]: The created question with its version history.

        Raises:
            HTTPException 400: Unknown category.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing AdminQuestionController.create_question")
            data = dict(payload)
            initial_version = data.pop("initial_version", None)
            await self._require_category(data["category_slug"])

            question = await self.CRUDQuestion.create(
                obj_in={**data, "status": QuestionStatus.DRAFT}
            )
            if initial_version is not None:
                await self._create_version(
                    admin=admin, question_id=question.id, payload=initial_version
                )
            return await self.get_question(question_id=question.id)
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AdminQuestionController.create_question: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def update_question(
        self, *, question_id: uuid.UUID, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Update a question's taxonomy.

        Taxonomy is deliberately mutable while grading content is not: recategorising a question
        changes which weakness it counts toward from now on, but it does not change what any past
        grade meant.

        Args:
            question_id: Question ID.
            payload: Category, subcategory, or difficulty changes.

        Returns:
            dict[str, Any]: The updated question with its version history.

        Raises:
            HTTPException 400: No fields supplied, or an unknown category.
            HTTPException 404: No such question.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing AdminQuestionController.update_question")
            if not payload:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
                )
            await self._require_question(question_id)
            if payload.get("category_slug") is not None:
                await self._require_category(payload["category_slug"])

            await self.CRUDQuestion.update(question_id=question_id, obj_in=payload)
            return await self.get_question(question_id=question_id)
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AdminQuestionController.update_question: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def set_status(
        self, *, question_id: uuid.UUID, new_status: QuestionStatus
    ) -> dict[str, Any]:
        """
        Activate or retire a question.

        Activation requires a published version. Without that guard a content owner could put a
        question into the live pool with no rubric behind it, and every student who drew it would
        get a grading failure rather than a grade — the failure surfacing far from its cause.

        Retirement is always permitted and never deletes anything: past attempts stay attributable
        to the version that graded them, the question simply stops being selected.

        Args:
            question_id: Question ID.
            new_status: Target lifecycle state.

        Returns:
            dict[str, Any]: The updated question with its version history.

        Raises:
            HTTPException 404: No such question.
            HTTPException 409: Activation requested without a published version.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing AdminQuestionController.set_status")
            question = await self._require_question(question_id)

            if new_status == QuestionStatus.ACTIVE:
                published = next(
                    (
                        version
                        for version in question.versions
                        if version.status == QuestionVersionStatus.PUBLISHED
                    ),
                    None,
                )
                if published is None:
                    logging.warning(
                        f"Refused to activate question {question_id} with no published version"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "Publish a version before activating this question. An active "
                            "question with no rubric cannot be graded."
                        ),
                    )

            await self.CRUDQuestion.update(question_id=question_id, obj_in={"status": new_status})
            return await self.get_question(question_id=question_id)
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AdminQuestionController.set_status: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def create_version(
        self, *, admin: User, question_id: uuid.UUID, payload: dict[str, Any]
    ) -> QuestionVersion:
        """
        Create a new version of a question's grading content.

        Args:
            admin: The acting administrator, recorded as the author.
            question_id: Question the version belongs to.
            payload: Prompt, ideal answer, concepts, mistakes, rubric, and a ``publish`` flag.

        Returns:
            QuestionVersion: The created version.

        Raises:
            HTTPException 404: No such question.
            HTTPException 422: Publication was requested and the rubric is incomplete.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing AdminQuestionController.create_version")
            await self._require_question(question_id)
            return await self._create_version(admin=admin, question_id=question_id, payload=payload)
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AdminQuestionController.create_version: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def update_version(
        self, *, question_id: uuid.UUID, version_id: uuid.UUID, payload: dict[str, Any]
    ) -> QuestionVersion:
        """
        Edit a draft version's content in place.

        Refuses published and superseded versions with 409. Those have graded, or could have
        graded, real attempts, and rewriting one would change retroactively what a past score
        meant — the one thing the version split exists to prevent.

        Args:
            question_id: Question the version must belong to.
            version_id: Version to edit.
            payload: Content fields to change.

        Returns:
            QuestionVersion: The updated draft.

        Raises:
            HTTPException 400: No fields supplied.
            HTTPException 404: No such version on this question.
            HTTPException 409: The version is published or superseded.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing AdminQuestionController.update_version")
            if not payload:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
                )
            await self.get_version(question_id=question_id, version_id=version_id)

            try:
                updated = await self.CRUDQuestionVersion.update_draft(
                    version_id=version_id, obj_in=self._normalise_content(payload)
                )
            except ValueError as error:
                logging.warning(f"Refused in-place edit of non-draft version {version_id}")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "This version has been published and cannot be edited. Create a new "
                        "version instead, so past grades keep their meaning."
                    ),
                ) from error

            if updated is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Question version not found"
                )
            return updated
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AdminQuestionController.update_version: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def publish_version(
        self, *, question_id: uuid.UUID, version_id: uuid.UUID
    ) -> QuestionVersion:
        """
        Publish a version, superseding the one it replaces.

        Validation runs before the write, so an incomplete rubric is rejected with a list of what
        to fix rather than a database constraint violation the interface cannot explain.

        Args:
            question_id: Question the version must belong to.
            version_id: Version to publish.

        Returns:
            QuestionVersion: The published version.

        Raises:
            HTTPException 404: No such version on this question.
            HTTPException 409: The version is already superseded.
            HTTPException 422: The rubric is incomplete.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing AdminQuestionController.publish_version")
            version = await self.get_version(question_id=question_id, version_id=version_id)

            if version.status == QuestionVersionStatus.SUPERSEDED:
                logging.warning(f"Refused to republish superseded version {version_id}")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "This version has already been superseded. Create a new version from it "
                        "rather than reinstating it."
                    ),
                )

            self._require_publishable(self._version_content(version))
            published = await self.CRUDQuestionVersion.publish(version_id=version_id)
            if published is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Question version not found"
                )
            logging.info(f"Published version {published.version} of question {question_id}")
            return published
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AdminQuestionController.publish_version: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def validate_version(
        self, *, question_id: uuid.UUID, version_id: uuid.UUID
    ) -> dict[str, Any]:
        """
        Report whether a version is complete enough to publish, without publishing it.

        Lets the editor show the same verdict the publish action would give, so an author is
        never surprised by a rejection at the moment they try to ship.

        Args:
            question_id: Question the version must belong to.
            version_id: Version to check.

        Returns:
            dict[str, Any]: Validity, blocking errors, and quality warnings.

        Raises:
            HTTPException 404: No such version on this question.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing AdminQuestionController.validate_version")
            version = await self.get_version(question_id=question_id, version_id=version_id)
            return self.RubricValidator.validate(version=self._version_content(version)).as_dict()
        except HTTPException:
            raise
        except Exception as error:
            logging.error(f"Error in AdminQuestionController.validate_version: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    # ----------------------------------------------------------------------------------
    # Internals
    # ----------------------------------------------------------------------------------

    async def _create_version(
        self, *, admin: User, question_id: uuid.UUID, payload: dict[str, Any]
    ) -> QuestionVersion:
        """
        Write a version and optionally publish it in the same request.

        Args:
            admin: The acting administrator, recorded as the author.
            question_id: Owning question.
            payload: Version content plus a ``publish`` flag.

        Returns:
            QuestionVersion: The created version, published when requested.

        Raises:
            HTTPException 422: Publication was requested and the rubric is incomplete.
        """
        data = self._normalise_content(payload)
        publish = bool(payload.get("publish", False))
        if publish:
            # Checked before the insert, so a rejected publish does not leave a stray draft
            # behind for the author to clean up.
            self._require_publishable(data)

        version = await self.CRUDQuestionVersion.create(
            obj_in={**data, "question_id": question_id, "created_by": admin.id}
        )
        if not publish:
            return version

        published = await self.CRUDQuestionVersion.publish(version_id=version.id)
        return published if published is not None else version

    def _require_publishable(self, content: dict[str, Any]) -> None:
        """
        Reject content that is not complete enough to grade against.

        Args:
            content: Version content fields.

        Raises:
            HTTPException 422: The rubric is incomplete, with the specific failures listed.
        """
        result = self.RubricValidator.validate(version=content)
        if result.is_valid:
            return
        logging.warning(f"Rejected publication of an incomplete rubric: {result.errors}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "This version is not complete enough to publish.",
                **result.as_dict(),
            },
        )

    @staticmethod
    def _normalise_content(payload: dict[str, Any]) -> dict[str, Any]:
        """
        Reduce a request payload to the version columns, dropping control flags.

        ``publish`` is an instruction, not content; letting it reach the model would raise an
        unmapped-attribute error at insert time.

        Args:
            payload: Raw request payload.

        Returns:
            dict[str, Any]: Only the fields a version row stores.
        """
        fields = ("prompt", "ideal_answer", "expected_concepts", "common_mistakes", "rubric")
        return {key: payload[key] for key in fields if key in payload}

    @staticmethod
    def _version_content(version: QuestionVersion) -> dict[str, Any]:
        """
        Extract a stored version's grading content for validation.

        Args:
            version: The stored version.

        Returns:
            dict[str, Any]: Content fields in the shape the validator expects.
        """
        return {
            "prompt": version.prompt,
            "ideal_answer": version.ideal_answer,
            "expected_concepts": version.expected_concepts,
            "common_mistakes": version.common_mistakes,
            "rubric": version.rubric,
        }

    async def _require_category(self, slug: str) -> None:
        """
        Verify a category exists before it is assigned to a question.

        Checked here rather than left to the foreign key so the caller gets a 400 naming the
        problem instead of a 500 from a constraint violation.

        Args:
            slug: Category slug.

        Raises:
            HTTPException 400: No such category.
        """
        if await self.CRUDCategory.get_by_slug(slug=slug) is None:
            logging.warning(f"Rejected an unknown category slug: {slug}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown category: {slug}"
            )

    async def _require_question(self, question_id: uuid.UUID) -> Question:
        """
        Load a question with its versions, or fail with 404.

        Args:
            question_id: Question ID.

        Returns:
            Question: The question with ``versions`` loaded.

        Raises:
            HTTPException 404: No such question.
        """
        question = await self.CRUDQuestion.get_with_versions(question_id=question_id)
        if question is None:
            logging.warning(f"No question found with id: {question_id}")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
        return question

    def _question_summary(self, question: Question) -> dict[str, Any]:
        """
        Build the admin list/detail payload for one question.

        Args:
            question: A question with its versions loaded.

        Returns:
            dict[str, Any]: Taxonomy, lifecycle, published version summary, and version count.
        """
        published = next(
            (
                version
                for version in question.versions
                if version.status == QuestionVersionStatus.PUBLISHED
            ),
            None,
        )
        return {
            "id": question.id,
            "source_key": question.source_key,
            "category_slug": question.category_slug,
            "subcategory": question.subcategory,
            "difficulty": question.difficulty,
            "status": question.status,
            "created_at": question.created_at,
            "updated_at": question.updated_at,
            "published_version": self._version_summary(published) if published else None,
            "version_count": len(question.versions),
        }

    @staticmethod
    def _version_summary(version: QuestionVersion) -> dict[str, Any]:
        """
        Build a version's identity and lifecycle, without its grading content.

        Used wherever history is listed. Omitting the content is not only a payload saving: it
        keeps rubrics out of the responses that are fetched most often.

        Args:
            version: The version to summarise.

        Returns:
            dict[str, Any]: Version identity, status, author, and creation time.
        """
        return {
            "id": version.id,
            "version": version.version,
            "status": version.status,
            "created_by": version.created_by,
            "created_at": version.created_at,
        }
