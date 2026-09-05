"""Tests that the database itself enforces the product's core invariants.

These deliberately bypass the application layer and write directly through CRUD, because the
point is not that the controllers are careful — it is that the schema refuses the bad state even
when they are not. Each test corresponds to an invariant whose violation would silently corrupt
the learning evidence the whole product is built on.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from core.constants.enums import (
    Band,
    EntitlementStatus,
    GradingStatus,
    QuestionVersionStatus,
    SessionStatus,
    SessionType,
)
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.billing_crud import CRUDEntitlement
from core.cruds.question_crud import CRUDQuestionVersion
from core.cruds.session_crud import CRUDSession
from core.cruds.skill_score_crud import CRUDSkillScore
from core.cruds.user_crud import CRUDProfile, CRUDUser
from core.database.database import session
from tests.conftest import requires_database
from tests.factories import (
    graded_result,
    make_attempt,
    make_gradeable_question,
    make_question,
    make_question_version,
    make_session,
    make_user,
)

pytestmark = [requires_database, pytest.mark.usefixtures("migrated_database")]


class TestAnswerIsNeverLost:
    """A grading failure must never be indistinguishable from a bad answer."""

    async def test_failed_grading_cannot_carry_a_score(self) -> None:
        """The schema rejects a failed attempt that also has a score."""
        user = await make_user()
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )

        # Written as raw SQL deliberately. The CRUD layer cannot produce this state, which is
        # precisely why the guarantee is asserted at the database: it has to survive a future code
        # path, a data migration, or a manual fix that is less careful than this one.
        with pytest.raises(IntegrityError):
            async with session() as db:
                await db.execute(
                    text(
                        "UPDATE attempts SET grading_status = :status, score = 0, band = :band"
                        " WHERE id = :id"
                    ),
                    {"status": GradingStatus.FAILED, "band": Band.NEEDS_WORK, "id": attempt.id},
                )

    async def test_marking_failed_preserves_the_answer_and_leaves_score_null(self) -> None:
        """A failed grading keeps the student's answer and records no score."""
        user = await make_user()
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
            answer="A partially correct answer worth preserving.",
        )

        failed = await CRUDAttempt().set_grading_status(
            attempt_id=attempt.id, status=GradingStatus.FAILED, increment_retry=True
        )

        assert failed is not None
        assert failed.answer == "A partially correct answer worth preserving."
        assert failed.score is None
        assert failed.band is None
        assert failed.retry_count == 1

    async def test_graded_attempt_must_carry_its_evidence(self) -> None:
        """The schema rejects an attempt claiming GRADED without a score and band."""
        user = await make_user()
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )

        with pytest.raises(IntegrityError):
            await CRUDAttempt().set_grading_status(
                attempt_id=attempt.id, status=GradingStatus.GRADED
            )


class TestDuplicateSubmissionProtection:
    """A double click or client retry must not create two attempts."""

    async def test_second_attempt_for_same_question_in_session_is_rejected(self) -> None:
        """The unique constraint on (session_id, question_id) blocks a duplicate submit."""
        user = await make_user()
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )

        with pytest.raises(IntegrityError):
            await make_attempt(
                user_id=user.id,
                session_id=session_row.id,
                question_id=question.id,
                question_version_id=version.id,
                answer="A second, different answer.",
            )

    async def test_existing_attempt_is_retrievable_so_a_retry_can_return_it(self) -> None:
        """A repeated submission can find the original attempt instead of failing."""
        user = await make_user()
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        original = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )

        found = await CRUDAttempt().get_for_session_question(
            session_id=session_row.id, question_id=question.id
        )

        assert found is not None
        assert found.id == original.id


class TestGradingHistoryIsImmutable:
    """Editing a rubric must never change what a past grade meant."""

    async def test_publishing_a_new_version_supersedes_the_previous_one(self) -> None:
        """Only one version stays published, and the old one becomes superseded."""
        question = await make_question()
        first = await make_question_version(question_id=question.id)
        second = await make_question_version(
            question_id=question.id, published=False, prompt="A revised prompt."
        )

        await CRUDQuestionVersion().publish(version_id=second.id)

        versions = {
            version.version: version.status
            for version in await CRUDQuestionVersion().list_for_question(question_id=question.id)
        }
        assert versions[first.version] == QuestionVersionStatus.SUPERSEDED
        assert versions[second.version] == QuestionVersionStatus.PUBLISHED

        published = await CRUDQuestionVersion().get_published(question_id=question.id)
        assert published is not None
        assert published.id == second.id

    async def test_a_superseded_version_still_backs_its_historical_attempt(self) -> None:
        """An attempt keeps pointing at the version it was graded against, after a rubric change."""
        user = await make_user()
        question = await make_question()
        original_version = await make_question_version(question_id=question.id)
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {
                    "position": 0,
                    "question_id": question.id,
                    "question_version_id": original_version.id,
                }
            ],
        )
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=original_version.id,
        )
        await CRUDAttempt().set_grade_result(attempt_id=attempt.id, result=graded_result())

        revised = await make_question_version(
            question_id=question.id, published=False, prompt="Rewritten prompt."
        )
        await CRUDQuestionVersion().publish(version_id=revised.id)

        stored = await CRUDAttempt().get_by_id(attempt_id=attempt.id)
        assert stored is not None
        assert stored.question_version_id == original_version.id
        assert stored.score == 82

    async def test_two_versions_cannot_be_published_at_once(self) -> None:
        """The partial unique index makes 'which rubric grades this now' unambiguous."""
        question = await make_question()
        await make_question_version(question_id=question.id)
        second = await make_question_version(question_id=question.id, published=False)

        with pytest.raises(IntegrityError):
            await CRUDQuestionVersion().create(
                obj_in={
                    "question_id": question.id,
                    "version": second.version + 1,
                    "prompt": "Third",
                    "ideal_answer": "Answer",
                    "expected_concepts": [{"key": "a", "label": "A"}],
                    "common_mistakes": [],
                    "rubric": {},
                    "status": QuestionVersionStatus.PUBLISHED,
                }
            )


class TestRubricCompleteness:
    """A question cannot enter the graded pool without the content needed to grade it."""

    async def test_publishing_without_expected_concepts_is_rejected(self) -> None:
        """The schema refuses a published version with an empty concept list."""
        question = await make_question()

        with pytest.raises(IntegrityError):
            await CRUDQuestionVersion().create(
                obj_in={
                    "question_id": question.id,
                    "prompt": "A prompt",
                    "ideal_answer": "An ideal answer",
                    "expected_concepts": [],
                    "common_mistakes": [],
                    "rubric": {},
                    "status": QuestionVersionStatus.PUBLISHED,
                }
            )

    async def test_publishing_without_an_ideal_answer_is_rejected(self) -> None:
        """The schema refuses a published version whose ideal answer is blank."""
        question = await make_question()

        with pytest.raises(IntegrityError):
            await CRUDQuestionVersion().create(
                obj_in={
                    "question_id": question.id,
                    "prompt": "A prompt",
                    "ideal_answer": "   ",
                    "expected_concepts": [{"key": "a", "label": "A"}],
                    "common_mistakes": [],
                    "rubric": {},
                    "status": QuestionVersionStatus.PUBLISHED,
                }
            )

    async def test_an_incomplete_draft_is_allowed(self) -> None:
        """Drafts may be incomplete; only publishing requires a complete rubric."""
        question = await make_question()

        draft = await CRUDQuestionVersion().create(
            obj_in={
                "question_id": question.id,
                "prompt": "A prompt still being written",
                "ideal_answer": "",
                "expected_concepts": [],
                "common_mistakes": [],
                "rubric": {},
                "status": QuestionVersionStatus.DRAFT,
            }
        )

        assert draft.status == QuestionVersionStatus.DRAFT

    async def test_a_question_without_a_published_version_is_not_selectable(self) -> None:
        """An active question with only a draft rubric never reaches a session."""
        from core.cruds.question_crud import CRUDQuestion

        question = await make_question()
        await make_question_version(question_id=question.id, published=False)

        selectable = await CRUDQuestion().list_selectable(category_slug=question.category_slug)

        assert question.id not in {item.id for item in selectable}


class TestMasteryIsAlwaysEvidenceBacked:
    """A readiness number with nothing behind it is the one thing this product cannot show."""

    async def test_a_score_with_no_evidence_is_rejected(self) -> None:
        """The schema refuses a mastery score backed by zero graded attempts."""
        user = await make_user()

        with pytest.raises(IntegrityError):
            await CRUDSkillScore().upsert(
                user_id=user.id, category_slug="valuation", score=72, evidence_count=0
            )

    async def test_upsert_carries_the_previous_score_forward(self) -> None:
        """Recomputing a score preserves the prior value so trends can be shown."""
        user = await make_user()
        crud = CRUDSkillScore()

        await crud.upsert(user_id=user.id, category_slug="valuation", score=54, evidence_count=3)
        updated = await crud.upsert(
            user_id=user.id, category_slug="valuation", score=61, evidence_count=5
        )

        assert updated.score == 61
        assert updated.previous_score == 54
        assert updated.evidence_count == 5

    async def test_scores_outside_zero_to_one_hundred_are_rejected(self) -> None:
        """Mastery is a 0-100 scale and the database enforces it."""
        user = await make_user()

        with pytest.raises(IntegrityError):
            await CRUDSkillScore().upsert(
                user_id=user.id, category_slug="valuation", score=140, evidence_count=2
            )


class TestConsentDefaultsOff:
    """Recruiting consent must never be implied by signing up."""

    async def test_a_new_profile_has_consent_disabled(self) -> None:
        """Consent defaults to false without the caller having to say so."""
        user = await make_user()

        profile = await CRUDProfile().create(user_id=user.id, obj_in={"school": "Example College"})

        assert profile.recruiting_consent is False
        assert profile.recruiting_consent_updated_at is None

    async def test_consent_cannot_be_granted_through_profile_creation(self) -> None:
        """Passing consent at signup time is ignored; it needs the explicit consent path."""
        user = await make_user()

        profile = await CRUDProfile().create(
            user_id=user.id, obj_in={"school": "Example College", "recruiting_consent": True}
        )

        assert profile.recruiting_consent is False

    async def test_granting_consent_records_when_it_happened(self) -> None:
        """Consent is auditable: granting it stamps a timestamp."""
        user = await make_user()
        await CRUDProfile().create(user_id=user.id)

        updated = await CRUDProfile().update(user_id=user.id, obj_in={"recruiting_consent": True})

        assert updated is not None
        assert updated.recruiting_consent is True
        assert updated.recruiting_consent_updated_at is not None

    async def test_consent_is_revocable(self) -> None:
        """Consent can be withdrawn after being granted."""
        user = await make_user()
        await CRUDProfile().create(user_id=user.id)
        await CRUDProfile().update(user_id=user.id, obj_in={"recruiting_consent": True})

        revoked = await CRUDProfile().update(user_id=user.id, obj_in={"recruiting_consent": False})

        assert revoked is not None
        assert revoked.recruiting_consent is False


class TestAccountIntegrity:
    """Identity constraints that prevent unreachable or duplicate accounts."""

    async def test_email_is_stored_and_matched_case_insensitively(self) -> None:
        """A login differing only by casing resolves to the same account."""
        user = await make_user(email="Student.Name@Example.EDU")

        assert user.email == "student.name@example.edu"
        found = await CRUDUser().get_by_email(email="STUDENT.NAME@EXAMPLE.EDU")
        assert found is not None
        assert found.id == user.id

    async def test_duplicate_email_is_rejected(self) -> None:
        """Two accounts cannot share an email address."""
        await make_user(email="taken@example.edu")

        with pytest.raises(IntegrityError):
            await make_user(email="Taken@Example.edu")

    async def test_an_account_must_keep_a_way_to_sign_in(self) -> None:
        """An account with neither a password nor a Google identity is rejected."""
        with pytest.raises(IntegrityError):
            await CRUDUser().create(
                obj_in={"email": "nologin@example.edu", "password_hash": None, "google_sub": None}
            )

    async def test_deleting_a_user_removes_their_profile(self) -> None:
        """Profile data is cascaded on account deletion, supporting the deletion requirement."""
        user = await make_user()
        await CRUDProfile().create(user_id=user.id)

        async with session() as db:
            await db.execute(text("DELETE FROM users WHERE id = :id"), {"id": user.id})

        assert await CRUDProfile().get_by_user_id(user_id=user.id) is None


class TestGradingProvenanceCannotBeDeleted:
    """Historical grades must remain attributable to the rubric that produced them."""

    async def test_a_question_version_with_attempts_cannot_be_deleted(self) -> None:
        """The RESTRICT foreign key protects the provenance of a graded attempt."""
        user = await make_user()
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )

        with pytest.raises(IntegrityError):
            async with session() as db:
                await db.execute(
                    text("DELETE FROM question_versions WHERE id = :id"), {"id": version.id}
                )


class TestSessionLifecycle:
    """Session state and its finish time must never disagree."""

    async def test_an_in_progress_session_cannot_have_a_finish_time(self) -> None:
        """The schema rejects an in-progress session that claims to have finished."""
        user = await make_user()
        row = await make_session(user_id=user.id)

        with pytest.raises(IntegrityError):
            async with session() as db:
                await db.execute(
                    text("UPDATE sessions SET finished_at = now() WHERE id = :id"), {"id": row.id}
                )

    async def test_finishing_a_session_sets_status_and_timestamp_together(self) -> None:
        """Completing a session records both its terminal status and when it ended."""
        user = await make_user()
        row = await make_session(user_id=user.id)

        finished = await CRUDSession().finish(session_id=row.id, status=SessionStatus.COMPLETED)

        assert finished is not None
        assert finished.status == SessionStatus.COMPLETED
        assert finished.finished_at is not None

    async def test_a_session_cannot_ask_the_same_question_twice(self) -> None:
        """The unique constraint keeps a composition from repeating a question."""
        user = await make_user()
        question, version = await make_gradeable_question()

        with pytest.raises(IntegrityError):
            await make_session(
                user_id=user.id,
                questions=[
                    {"position": 0, "question_id": question.id, "question_version_id": version.id},
                    {"position": 1, "question_id": question.id, "question_version_id": version.id},
                ],
            )

    async def test_composition_is_stored_in_order_for_resume(self) -> None:
        """A refreshed session recovers its exact server-decided question order."""
        user = await make_user()
        composition = []
        for position in range(3):
            question, version = await make_gradeable_question()
            composition.append(
                {
                    "position": position,
                    "question_id": question.id,
                    "question_version_id": version.id,
                }
            )
        created = await make_session(user_id=user.id, questions=composition)

        resumed = await CRUDSession().get_with_questions(session_id=created.id)

        assert resumed is not None
        assert [item.position for item in resumed.questions] == [0, 1, 2]
        assert [item.question_id for item in resumed.questions] == [
            row["question_id"] for row in composition
        ]


class TestEntitlementsAreServerAuthoritative:
    """Free access is the absence of a grant, and expiry is evaluated at read time."""

    async def test_a_user_with_no_grant_has_no_entitlement(self) -> None:
        """A new account is on the free tier by default."""
        user = await make_user()

        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None

    async def test_an_active_grant_is_returned(self) -> None:
        """A current grant is found by the access check."""
        from datetime import timedelta

        from tests.factories import utc_now

        user = await make_user()
        await CRUDEntitlement().create(
            obj_in={
                "user_id": user.id,
                "entitlement": "pro",
                "active_from": utc_now() - timedelta(days=1),
                "active_until": utc_now() + timedelta(days=29),
                "status": EntitlementStatus.ACTIVE,
            }
        )

        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is not None

    async def test_an_elapsed_grant_stops_granting_access_immediately(self) -> None:
        """An expired Season Pass loses access without waiting for a reconciliation job."""
        from datetime import timedelta

        from tests.factories import utc_now

        user = await make_user()
        await CRUDEntitlement().create(
            obj_in={
                "user_id": user.id,
                "entitlement": "season_pass",
                "active_from": utc_now() - timedelta(days=200),
                "active_until": utc_now() - timedelta(days=1),
                # Still marked active: the nightly job has not run yet.
                "status": EntitlementStatus.ACTIVE,
            }
        )

        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None

    async def test_a_future_grant_does_not_grant_access_yet(self) -> None:
        """A grant that has not started is not usable."""
        from datetime import timedelta

        from tests.factories import utc_now

        user = await make_user()
        await CRUDEntitlement().create(
            obj_in={
                "user_id": user.id,
                "entitlement": "pro",
                "active_from": utc_now() + timedelta(days=1),
                "status": EntitlementStatus.ACTIVE,
            }
        )

        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None


class TestAnswerBounds:
    """The answer length guardrail is enforced by the database, not only the composer."""

    async def test_an_oversized_answer_is_rejected(self) -> None:
        """A client bypassing the form cannot push an unbounded payload into a paid model call."""
        user = await make_user()
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )

        with pytest.raises(IntegrityError):
            await make_attempt(
                user_id=user.id,
                session_id=session_row.id,
                question_id=question.id,
                question_version_id=version.id,
                answer="x" * 2001,
            )

    async def test_an_empty_answer_is_rejected(self) -> None:
        """An empty submission is not a gradeable attempt."""
        user = await make_user()
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )

        with pytest.raises(IntegrityError):
            await make_attempt(
                user_id=user.id,
                session_id=session_row.id,
                question_id=question.id,
                question_version_id=version.id,
                answer="",
            )


class TestSessionTypeIsolation:
    """Free-tier counting depends on session types being distinguishable."""

    async def test_sessions_are_counted_per_type(self) -> None:
        """Diagnostic and practice sessions are counted separately."""
        user = await make_user()
        await make_session(user_id=user.id, type=SessionType.DIAGNOSTIC)
        await make_session(user_id=user.id, type=SessionType.PRACTICE)
        await make_session(user_id=user.id, type=SessionType.PRACTICE)

        crud = CRUDSession()
        assert await crud.count_by_type(user_id=user.id, session_type=SessionType.DIAGNOSTIC) == 1
        assert await crud.count_by_type(user_id=user.id, session_type=SessionType.PRACTICE) == 2

    async def test_another_users_sessions_are_not_counted(self) -> None:
        """Counting is scoped to the owning user."""
        user = await make_user()
        other = await make_user()
        await make_session(user_id=other.id, type=SessionType.DIAGNOSTIC)

        count = await CRUDSession().count_by_type(
            user_id=user.id, session_type=SessionType.DIAGNOSTIC
        )

        assert count == 0


class TestGradeAuditTrail:
    """Every grading call must be reconstructible, including the ones that failed."""

    async def test_failed_grading_calls_are_recorded(self) -> None:
        """A provider failure produces an audit record, not silence."""
        from core.constants.enums import ValidationStatus
        from core.cruds.attempt_crud import CRUDGradeEvent

        user = await make_user()
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )

        await CRUDGradeEvent().create(
            obj_in={
                "attempt_id": attempt.id,
                "provider": "openrouter",
                "model": "test-model",
                "prompt_version": "v1",
                "rubric_version": version.version,
                "validation_status": ValidationStatus.INVALID_SCHEMA,
                "error_message": "Model returned prose instead of JSON",
                "retry_count": 1,
            }
        )

        events = await CRUDGradeEvent().list_for_attempt(attempt_id=attempt.id)
        assert len(events) == 1
        assert events[0].validation_status == ValidationStatus.INVALID_SCHEMA

    async def test_an_unknown_validation_status_is_rejected(self) -> None:
        """The audit trail's validation vocabulary is constrained by the schema."""
        from core.cruds.attempt_crud import CRUDGradeEvent

        user = await make_user()
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )

        with pytest.raises(IntegrityError):
            await CRUDGradeEvent().create(
                obj_in={
                    "attempt_id": attempt.id,
                    "provider": "openrouter",
                    "model": "test-model",
                    "prompt_version": "v1",
                    "rubric_version": 1,
                    "validation_status": "made_up_status",
                }
            )


class TestGradeFlags:
    """A dispute is a statement, not a vote to be repeated."""

    async def test_a_user_can_only_flag_an_attempt_once(self) -> None:
        """The unique constraint prevents repeated flags on the same attempt."""
        from core.constants.enums import GradeFlagReason
        from core.cruds.attempt_crud import CRUDGradeFlag

        user = await make_user()
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )
        flag_data = {
            "attempt_id": attempt.id,
            "user_id": user.id,
            "reason": GradeFlagReason.SCORE_TOO_LOW,
        }
        await CRUDGradeFlag().create(obj_in=flag_data)

        with pytest.raises(IntegrityError):
            await CRUDGradeFlag().create(obj_in=dict(flag_data))

    async def test_a_resolved_flag_records_when_it_was_closed(self) -> None:
        """The schema requires a closed flag to carry its resolution time."""
        from core.constants.enums import GradeFlagReason, GradeFlagStatus
        from core.cruds.attempt_crud import CRUDGradeFlag

        user = await make_user()
        admin = await make_user(is_admin=True)
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )
        flag = await CRUDGradeFlag().create(
            obj_in={
                "attempt_id": attempt.id,
                "user_id": user.id,
                "reason": GradeFlagReason.WRONG_CONCEPTS,
            }
        )

        resolved = await CRUDGradeFlag().resolve(
            flag_id=flag.id,
            status=GradeFlagStatus.RESOLVED,
            reviewer_id=admin.id,
            resolution="Rubric corrected and attempt re-graded.",
        )

        assert resolved is not None
        assert resolved.resolved_at is not None
        assert resolved.reviewer_id == admin.id


class TestUnknownIdentifiers:
    """CRUD reads return None rather than raising for a missing row."""

    async def test_reading_a_missing_attempt_returns_none(self) -> None:
        """A random attempt ID resolves to None, not an exception."""
        assert await CRUDAttempt().get_by_id(attempt_id=uuid.uuid4()) is None

    async def test_updating_a_missing_user_returns_none(self) -> None:
        """Updating a nonexistent user reports absence instead of failing."""
        assert await CRUDUser().update(user_id=uuid.uuid4(), obj_in={"status": "suspended"}) is None
