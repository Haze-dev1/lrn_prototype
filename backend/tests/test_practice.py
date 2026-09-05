"""Tests for adaptive practice selection.

The PRD requires selection to be deterministic and explainable, so these tests assert on *why* a
question was chosen, not only that a set of the right length came back. Each signal — review due,
weakness, novelty, difficulty fit — is driven in isolation, then together, then at the edges where
a naive implementation quietly does the wrong thing.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from core.constants.enums import GradingStatus, SessionStatus, SessionType
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.question_crud import CRUDQuestion
from core.cruds.session_crud import CRUDSession
from core.cruds.skill_score_crud import CRUDSkillScore
from core.cruds.user_crud import CRUDUser
from core.services.questions.seed_service import QuestionSeeder
from core.services.sessions.practice_service import (
    PRACTICE_SET_SIZES,
    REVIEW_INTERVALS_DAYS,
    PracticeComposeError,
    PracticeComposer,
)
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

PASSWORD = "correct-horse-battery-staple"
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

pytestmark = [requires_database, pytest.mark.usefixtures("migrated_database")]


async def signed_in_user(client: AsyncClient, *, prefix: str = "student"):
    """
    Register a fresh account, leave the client signed in, and return the user row.

    Args:
        client: HTTP client bound to the application.
        prefix: Readable prefix for the account's email address.

    Returns:
        User: The registered user.
    """
    email = f"{prefix}-{uuid.uuid4().hex[:12]}@example.edu"
    response = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201
    user = await CRUDUser().get_by_email(email=email)
    assert user is not None
    return user


async def record_graded_attempt(*, user_id, question, version, score: int, graded_at: datetime):
    """
    Give a user a graded attempt at one question, at a chosen point in time.

    Args:
        user_id: Owning user ID.
        question: The question answered.
        version: The version graded against.
        score: The score awarded.
        graded_at: When it was graded.

    Returns:
        Attempt: The graded attempt.
    """
    session_row = await make_session(
        user_id=user_id,
        type=SessionType.PRACTICE,
        status=SessionStatus.COMPLETED,
        finished_at=graded_at,
        questions=[{"position": 0, "question_id": question.id, "question_version_id": version.id}],
    )
    attempt = await make_attempt(
        user_id=user_id,
        session_id=session_row.id,
        question_id=question.id,
        question_version_id=version.id,
    )
    await CRUDAttempt().set_grade_result(attempt_id=attempt.id, result=graded_result(score=score))

    # set_grade_result stamps graded_at as "now"; the spacing rules are all about age, so the
    # timestamp has to be moved deliberately for a test to mean anything.
    from sqlalchemy import text as sql_text

    from core.database.database import session as db_session

    async with db_session() as db:
        await db.execute(
            sql_text("UPDATE attempts SET graded_at = :at, submitted_at = :at WHERE id = :id"),
            {"at": graded_at, "id": attempt.id},
        )
    return attempt


async def compose_for(user_id, *, size: int = 5, category_slug: str | None = None, now=NOW):
    """
    Compose a practice set and return the selected questions with the rationale.

    Args:
        user_id: The student.
        size: Requested set size.
        category_slug: Optional category restriction.
        now: Reference time.

    Returns:
        tuple[list, dict]: Selected questions, and the stored rationale.
    """
    composition, rationale = await PracticeComposer().compose(
        user_id=user_id, size=size, category_slug=category_slug, now=now
    )
    questions = [
        await CRUDQuestion().get_by_id(question_id=row["question_id"]) for row in composition
    ]
    return questions, rationale


class TestSetSizes:
    """The product offers three lengths."""

    @pytest.mark.parametrize("size", PRACTICE_SET_SIZES)
    async def test_each_offered_size_is_composed(self, size: int) -> None:
        """5, 10 and 20 all produce a full set from the shipped bank."""
        await QuestionSeeder().run()
        user = await make_user()

        questions, _ = await compose_for(user.id, size=size)

        assert len(questions) == size

    async def test_positions_are_sequential(self) -> None:
        """Gaps in the stored order would break resumption."""
        await QuestionSeeder().run()
        user = await make_user()

        composition, _ = await PracticeComposer().compose(user_id=user.id, size=10, now=NOW)

        assert [row["position"] for row in composition] == list(range(10))

    async def test_no_question_appears_twice(self) -> None:
        """A repeated question wastes a slot in a short set."""
        await QuestionSeeder().run()
        user = await make_user()

        questions, _ = await compose_for(user.id, size=20)

        assert len({question.id for question in questions}) == 20

    async def test_a_set_larger_than_the_bank_returns_what_exists(self) -> None:
        """A thin bank yields a short set rather than failing or repeating questions."""
        for index in range(3):
            question = await make_question(category_slug="dcf", difficulty=index + 1)
            await make_question_version(question_id=question.id)
        user = await make_user()

        questions, _ = await compose_for(user.id, size=20)

        assert len(questions) == 3


class TestNovelty:
    """A student with no history."""

    async def test_a_new_student_gets_only_unseen_questions(self) -> None:
        """With no history every question is new, and the rationale says so."""
        await QuestionSeeder().run()
        user = await make_user()

        questions, rationale = await compose_for(user.id, size=5)

        assert rationale["new_count"] == 5
        assert rationale["review_due_count"] == 0
        assert "new to you" in rationale["explanation"]

    async def test_a_new_student_is_told_there_is_no_evidence_yet(self) -> None:
        """The explanation must not claim a weakest category that has not been measured."""
        await QuestionSeeder().run()
        user = await make_user()

        _, rationale = await compose_for(user.id, size=5)

        assert "no graded evidence yet" in rationale["explanation"]


class TestSpacedRepetition:
    """Missed questions come back on a schedule."""

    async def test_a_recent_miss_is_not_yet_due(self) -> None:
        """Repeating a question the day after missing it is cramming, not spacing."""
        await QuestionSeeder().run()
        user = await make_user()
        question, version = await make_gradeable_question()
        await record_graded_attempt(
            user_id=user.id,
            question=question,
            version=version,
            score=30,
            graded_at=NOW - timedelta(days=1),
        )

        questions, rationale = await compose_for(user.id, size=5)

        assert rationale["review_due_count"] == 0
        assert question.id not in {item.id for item in questions}

    async def test_a_miss_becomes_due_after_the_first_interval(self) -> None:
        """Two days after a first miss the question is eligible again."""
        await QuestionSeeder().run()
        user = await make_user()
        question, version = await make_gradeable_question()
        await record_graded_attempt(
            user_id=user.id,
            question=question,
            version=version,
            score=30,
            graded_at=NOW - timedelta(days=REVIEW_INTERVALS_DAYS[0]),
        )

        questions, rationale = await compose_for(user.id, size=5)

        assert question.id in {item.id for item in questions}
        assert rationale["review_due_count"] == 1
        assert "due for review" in rationale["explanation"]

    async def test_the_interval_lengthens_with_each_attempt(self) -> None:
        """A second miss waits seven days, not two.

        Without this the schedule would not be spaced repetition at all — it would repeat every
        two days forever, which is the behaviour spacing exists to avoid.
        """
        await QuestionSeeder().run()
        user = await make_user()
        question, version = await make_gradeable_question()
        for age in (30, 20):
            await record_graded_attempt(
                user_id=user.id,
                question=question,
                version=version,
                score=30,
                graded_at=NOW - timedelta(days=age),
            )

        # Two attempts, most recent three days ago: past the 2-day interval, inside the 7-day one.
        from sqlalchemy import text as sql_text

        from core.database.database import session as db_session

        async with db_session() as db:
            await db.execute(
                sql_text(
                    "UPDATE attempts SET graded_at = :at WHERE user_id = :uid "
                    "AND question_id = :qid AND graded_at = :old"
                ),
                {
                    "at": NOW - timedelta(days=3),
                    "uid": user.id,
                    "qid": question.id,
                    "old": NOW - timedelta(days=20),
                },
            )

        questions, _ = await compose_for(user.id, size=5)

        assert question.id not in {item.id for item in questions}

    async def test_a_well_answered_question_is_not_repeated(self) -> None:
        """Re-testing something a student just demonstrated wastes the slot."""
        await QuestionSeeder().run()
        user = await make_user()
        question, version = await make_gradeable_question()
        await record_graded_attempt(
            user_id=user.id,
            question=question,
            version=version,
            score=95,
            graded_at=NOW - timedelta(days=2),
        )

        questions, _ = await compose_for(user.id, size=20)

        assert question.id not in {item.id for item in questions}

    async def test_the_cooldown_stops_excluding_a_passed_question_eventually(self) -> None:
        """Knowledge decays, so a passed question stops being excluded outright.

        Deliberately tested against a small bank. Ceasing to be excluded is not the same as being
        chosen: once eligible the question competes on the weighted signals, and it will still
        lose to a question the student has never seen — which is the right ordering, since there
        is more to learn from the unseen one. The rule under test is the exclusion, so the test
        removes the competition.
        """
        user = await make_user()
        question, version = await make_gradeable_question()
        await record_graded_attempt(
            user_id=user.id,
            question=question,
            version=version,
            score=95,
            graded_at=NOW - timedelta(days=60),
        )

        questions, _ = await compose_for(user.id, size=5)

        assert question.id in {item.id for item in questions}

    async def test_an_unseen_question_outranks_one_already_answered_well(self) -> None:
        """Ordering between an eligible passed question and a new one.

        Pins the consequence of the test above: there is more to learn from a question the
        student has never met than from one they answered well two months ago.
        """
        await QuestionSeeder().run()
        user = await make_user()
        question, version = await make_gradeable_question()
        await record_graded_attempt(
            user_id=user.id,
            question=question,
            version=version,
            score=95,
            graded_at=NOW - timedelta(days=60),
        )

        questions, rationale = await compose_for(user.id, size=5)

        assert question.id not in {item.id for item in questions}
        assert rationale["new_count"] == 5


class TestWeaknessWeighting:
    """Weak categories are practised more."""

    async def test_the_weakest_category_drives_the_explanation(self) -> None:
        """The sentence a student reads names their actual weakest category."""
        await QuestionSeeder().run()
        user = await make_user()
        await CRUDSkillScore().upsert(
            user_id=user.id, category_slug="dcf", score=20, evidence_count=3
        )
        await CRUDSkillScore().upsert(
            user_id=user.id, category_slug="accounting", score=90, evidence_count=3
        )

        _, rationale = await compose_for(user.id, size=10)

        assert rationale["focus_category"] == "dcf"
        assert "weakest category at 20" in rationale["explanation"]

    async def test_a_weak_category_is_over_represented(self) -> None:
        """The engine actually shifts questions toward the weakness, not just the copy."""
        await QuestionSeeder().run()
        user = await make_user()
        await CRUDSkillScore().upsert(
            user_id=user.id, category_slug="dcf", score=10, evidence_count=3
        )
        for slug in ("accounting", "valuation", "lbo-private-equity"):
            await CRUDSkillScore().upsert(
                user_id=user.id, category_slug=slug, score=95, evidence_count=3
            )

        questions, _ = await compose_for(user.id, size=10)
        dcf = sum(1 for question in questions if question.category_slug == "dcf")

        assert dcf >= 2

    async def test_one_category_cannot_take_over_a_set(self) -> None:
        """A set entirely from one category is correct arithmetic and poor practice.

        A single sitting on one topic produces fatigue rather than coverage, so the share any one
        category may take is capped unless the student asked for it.
        """
        await QuestionSeeder().run()
        user = await make_user()
        await CRUDSkillScore().upsert(
            user_id=user.id, category_slug="dcf", score=1, evidence_count=5
        )

        questions, _ = await compose_for(user.id, size=10)
        dcf = sum(1 for question in questions if question.category_slug == "dcf")

        assert dcf <= 4
        assert len({question.category_slug for question in questions}) >= 3


class TestCategoryFocus:
    """Practising one category on request."""

    async def test_a_requested_category_fills_the_set(self) -> None:
        """The cap is lifted when the student explicitly asked for one category."""
        await QuestionSeeder().run()
        user = await make_user()

        questions, rationale = await compose_for(user.id, size=5, category_slug="dcf")

        assert {question.category_slug for question in questions} == {"dcf"}
        assert rationale["requested_category"] == "dcf"
        assert "You asked to practise" in rationale["explanation"]

    async def test_a_requested_category_yields_what_it_has(self) -> None:
        """Five questions requested from a category holding five gives five."""
        await QuestionSeeder().run()
        user = await make_user()

        questions, _ = await compose_for(user.id, size=20, category_slug="dcf")

        assert len(questions) == 5


class TestDifficultyProgression:
    """Sets open with something answerable."""

    async def test_a_set_is_ordered_easiest_first(self) -> None:
        """A set that opens with its hardest question is one a tired student abandons."""
        await QuestionSeeder().run()
        user = await make_user()

        questions, _ = await compose_for(user.id, size=10)
        difficulties = [question.difficulty for question in questions]

        assert difficulties == sorted(difficulties)

    async def test_a_set_spans_more_than_one_difficulty(self) -> None:
        """A flat set gives a student no sense of where their ceiling is.

        Difficulty fit is the only signal separating otherwise-equal candidates, so without a cap
        a student with no history gets every question at the single level nearest their assumed
        mastery — defensible ranking, worse session.
        """
        await QuestionSeeder().run()
        user = await make_user()

        questions, _ = await compose_for(user.id, size=5)

        assert len({question.difficulty for question in questions}) >= 2

    async def test_a_category_focused_set_still_spans_difficulties(self) -> None:
        """Asking for one category lifts the category cap, not the difficulty one."""
        await QuestionSeeder().run()
        user = await make_user()

        questions, _ = await compose_for(user.id, size=5, category_slug="dcf")

        assert len({question.difficulty for question in questions}) >= 2

    async def test_difficulty_tracks_mastery(self) -> None:
        """A strong student is not handed the easiest questions in the bank."""
        await QuestionSeeder().run()
        strong = await make_user()
        weak = await make_user()
        for slug in ("accounting", "dcf", "valuation", "lbo-private-equity"):
            await CRUDSkillScore().upsert(
                user_id=strong.id, category_slug=slug, score=95, evidence_count=5
            )
            await CRUDSkillScore().upsert(
                user_id=weak.id, category_slug=slug, score=10, evidence_count=5
            )

        strong_set, _ = await compose_for(strong.id, size=10)
        weak_set, _ = await compose_for(weak.id, size=10)

        strong_mean = sum(q.difficulty for q in strong_set) / len(strong_set)
        weak_mean = sum(q.difficulty for q in weak_set) / len(weak_set)
        assert strong_mean > weak_mean


class TestDeterminism:
    """A set must be reproducible and per-student."""

    async def test_composing_twice_gives_the_same_set(self) -> None:
        """Selection is a pure function of history and bank, so it can be explained later."""
        await QuestionSeeder().run()
        user = await make_user()

        first, _ = await compose_for(user.id, size=10)
        second, _ = await compose_for(user.id, size=10)

        assert [q.id for q in first] == [q.id for q in second]

    async def test_two_students_get_different_sets(self) -> None:
        """Identical histories must not produce one shareable set."""
        await QuestionSeeder().run()
        one = await make_user()
        two = await make_user()

        first, _ = await compose_for(one.id, size=10)
        second, _ = await compose_for(two.id, size=10)

        assert [q.id for q in first] != [q.id for q in second]


class TestEdgeCases:
    """Where a naive implementation quietly does the wrong thing."""

    async def test_an_empty_bank_fails_loudly(self) -> None:
        """No questions is a 409, not an empty session the student stares at."""
        user = await make_user()

        with pytest.raises(PracticeComposeError):
            await compose_for(user.id, size=5)

    async def test_a_student_who_has_passed_everything_recently(self) -> None:
        """Every question in cooldown must not produce a silent empty set."""
        question, version = await make_gradeable_question()
        user = await make_user()
        await record_graded_attempt(
            user_id=user.id,
            question=question,
            version=version,
            score=95,
            graded_at=NOW - timedelta(days=1),
        )

        with pytest.raises(PracticeComposeError, match="recently answered well"):
            await compose_for(user.id, size=5)

    async def test_an_ungraded_attempt_does_not_count_as_history(self) -> None:
        """A question answered but never graded is still unseen evidence-wise.

        Treating it as answered would silently drop it from future practice while contributing
        nothing to mastery — the student would never see it again and never be scored on it.
        """
        await QuestionSeeder().run()
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
            grading_status=GradingStatus.PENDING,
        )

        _, rationale = await compose_for(user.id, size=20)

        assert rationale["review_due_count"] == 0

    async def test_mastery_for_an_unmeasured_category_does_not_dominate(self) -> None:
        """An unmeasured category must not outrank one measured as genuinely weak.

        "Not measured" and "measured badly" are different claims, and treating the first as a
        score of zero would send every new student to whichever category happens to be untouched.
        """
        await QuestionSeeder().run()
        user = await make_user()
        await CRUDSkillScore().upsert(
            user_id=user.id, category_slug="dcf", score=5, evidence_count=5
        )

        questions, _ = await compose_for(user.id, size=10)
        dcf = sum(1 for question in questions if question.category_slug == "dcf")

        assert dcf >= 2


class TestPracticeApi:
    """Starting practice over HTTP."""

    async def test_starting_practice_returns_a_set(self, client: AsyncClient) -> None:
        """The happy path: a set, its questions, and why it was chosen."""
        await QuestionSeeder().run()
        await signed_in_user(client)

        response = await client.post("/v1/practice", json={"size": 10})
        body = response.json()

        assert response.status_code == 201
        assert body["type"] == SessionType.PRACTICE
        assert body["question_count"] == 10
        assert len(body["questions"]) == 10
        assert body["selection_rationale"]["explanation"]

    @pytest.mark.parametrize("size", [0, 3, 7, 100, -5])
    async def test_an_unsupported_size_is_rejected(self, client: AsyncClient, size: int) -> None:
        """A client asking for 500 questions is asking for 500 paid grading calls."""
        await QuestionSeeder().run()
        await signed_in_user(client)

        response = await client.post("/v1/practice", json={"size": size})

        assert response.status_code == 400

    async def test_an_unknown_category_is_rejected(self, client: AsyncClient) -> None:
        """A typo is reported rather than silently returning an unfocused set."""
        await QuestionSeeder().run()
        await signed_in_user(client)

        response = await client.post(
            "/v1/practice", json={"size": 5, "category_slug": "not-a-category"}
        )

        assert response.status_code == 400

    async def test_an_empty_bank_returns_409(self, client: AsyncClient) -> None:
        """The student is told there is nothing to practise, not given a broken session."""
        await signed_in_user(client)

        response = await client.post("/v1/practice", json={"size": 5})

        assert response.status_code == 409

    async def test_practice_requires_authentication(self, client: AsyncClient) -> None:
        """No session cookie, no practice."""
        response = await client.post("/v1/practice", json={"size": 5})

        assert response.status_code == 401

    async def test_starting_practice_abandons_the_previous_set(self, client: AsyncClient) -> None:
        """Choosing a new set means a new set; the old one must not linger as resumable."""
        await QuestionSeeder().run()
        user = await signed_in_user(client)
        first = (await client.post("/v1/practice", json={"size": 5})).json()

        second = (await client.post("/v1/practice", json={"size": 5})).json()
        active = await CRUDSession().get_active_for_user(
            user_id=user.id, session_type=SessionType.PRACTICE
        )

        assert second["id"] != first["id"]
        assert active is not None
        assert str(active.id) == second["id"]

    async def test_a_practice_set_carries_no_rubric_content(self, client: AsyncClient) -> None:
        """The same protection as the diagnostic, on a different entry point."""
        await QuestionSeeder().run()
        await signed_in_user(client)

        response = await client.post("/v1/practice", json={"size": 10})

        for field in ("ideal_answer", "expected_concepts", "common_mistakes", "rubric"):
            assert field not in response.text

    async def test_practice_does_not_disturb_an_open_diagnostic(self, client: AsyncClient) -> None:
        """The two flows are independent; starting practice must not abandon a diagnostic."""
        await QuestionSeeder().run()
        user = await signed_in_user(client)
        diagnostic = (await client.post("/v1/diagnostic")).json()

        await client.post("/v1/practice", json={"size": 5})
        still_open = await CRUDSession().get_active_for_user(
            user_id=user.id, session_type=SessionType.DIAGNOSTIC
        )

        assert still_open is not None
        assert str(still_open.id) == diagnostic["id"]
