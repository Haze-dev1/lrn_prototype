"""Tests for review history, grade disputes, and progress.

Review is where a student's evidence becomes actionable, so these tests cover the filters that
make an answer worth reopening, and the boundary that keeps one student's history private.
Progress is tested for the claims it makes: an unmeasured category must never render as a zero,
and "am I improving" must not be answerable from a single data point.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from core.constants.enums import GradingStatus, SessionStatus, SessionType
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.skill_score_crud import CRUDSkillScore
from core.cruds.user_crud import CRUDUser
from core.services.mastery.service import MasteryService
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


async def graded_attempt(
    *,
    user_id,
    category_slug: str = "valuation",
    score: int = 50,
    submitted_at: datetime | None = None,
    result_overrides: dict | None = None,
):
    """
    Create one graded attempt for a user in a chosen category.

    Args:
        user_id: Owning user ID.
        category_slug: Category the question belongs to.
        score: Score to award.
        submitted_at: When it was submitted, for recency filters.
        result_overrides: Extra grade fields, such as a concepts_missed list.

    Returns:
        Attempt: The graded attempt.
    """
    question = await make_question(category_slug=category_slug)
    version = await make_question_version(question_id=question.id)
    session_row = await make_session(
        user_id=user_id,
        questions=[{"position": 0, "question_id": question.id, "question_version_id": version.id}],
    )
    attempt = await make_attempt(
        user_id=user_id,
        session_id=session_row.id,
        question_id=question.id,
        question_version_id=version.id,
    )
    result = graded_result(score=score)
    result.update(result_overrides or {})
    await CRUDAttempt().set_grade_result(attempt_id=attempt.id, result=result)

    if submitted_at is not None:
        from sqlalchemy import text as sql_text

        from core.database.database import session as db_session

        async with db_session() as db:
            await db.execute(
                sql_text("UPDATE attempts SET submitted_at = :at, graded_at = :at WHERE id = :id"),
                {"at": submitted_at, "id": attempt.id},
            )
    return attempt


class TestReviewList:
    """The scannable history."""

    async def test_graded_attempts_are_listed_newest_first(self, client: AsyncClient) -> None:
        """The most recent work is what a student comes back to."""
        user = await signed_in_user(client)
        await graded_attempt(user_id=user.id, submitted_at=NOW - timedelta(days=5))
        await graded_attempt(user_id=user.id, submitted_at=NOW - timedelta(days=1))

        body = (await client.get("/v1/review")).json()
        stamps = [item["submitted_at"] for item in body["items"]]

        assert len(body["items"]) == 2
        assert stamps == sorted(stamps, reverse=True)

    async def test_an_item_carries_what_the_list_needs_and_no_more(
        self, client: AsyncClient
    ) -> None:
        """Enough to decide whether to open it; not the answer or the reference answer.

        A review list is scanned rather than read, and shipping every answer would make the page
        heavy to load and heavy to look at.
        """
        user = await signed_in_user(client)
        await graded_attempt(user_id=user.id, score=54)

        response = await client.get("/v1/review")
        item = response.json()["items"][0]

        assert item["score"] == 54
        assert item["band"]
        assert item["prompt"]
        assert item["category_name"]
        assert "answer" not in item
        assert "ideal_answer" not in response.text
        assert "feedback" not in item

    async def test_ungraded_attempts_are_excluded(self, client: AsyncClient) -> None:
        """An answer with no grade has nothing to review."""
        user = await signed_in_user(client)
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

        body = (await client.get("/v1/review")).json()

        assert body["items"] == []

    async def test_an_empty_history_returns_an_empty_page(self, client: AsyncClient) -> None:
        """A new student sees an empty list, not an error."""
        await signed_in_user(client)

        response = await client.get("/v1/review")

        assert response.status_code == 200
        assert response.json()["items"] == []
        assert response.json()["next_cursor"] is None

    async def test_pagination_advances(self, client: AsyncClient) -> None:
        """A full page carries a cursor; following it returns different attempts."""
        user = await signed_in_user(client)
        for day in range(4):
            await graded_attempt(user_id=user.id, submitted_at=NOW - timedelta(days=day))

        first = (await client.get("/v1/review", params={"limit": 2})).json()
        assert first["next_cursor"] is not None

        second = (
            await client.get("/v1/review", params={"limit": 2, "before": first["next_cursor"]})
        ).json()

        assert {item["id"] for item in second["items"]}.isdisjoint(
            {item["id"] for item in first["items"]}
        )

    async def test_the_final_page_has_no_cursor(self, client: AsyncClient) -> None:
        """An exhausted listing reports null rather than looping."""
        user = await signed_in_user(client)
        await graded_attempt(user_id=user.id)

        body = (await client.get("/v1/review", params={"limit": 20})).json()

        assert body["next_cursor"] is None


class TestReviewFilters:
    """The filters that make an answer worth reopening."""

    async def test_filtering_by_category(self, client: AsyncClient) -> None:
        """Working on one weakness at a time."""
        user = await signed_in_user(client)
        await graded_attempt(user_id=user.id, category_slug="dcf")
        await graded_attempt(user_id=user.id, category_slug="valuation")

        body = (await client.get("/v1/review", params={"category_slug": "dcf"})).json()

        assert {item["category_slug"] for item in body["items"]} == {"dcf"}

    async def test_filtering_by_score(self, client: AsyncClient) -> None:
        """The answers worth revisiting are the ones that went badly."""
        user = await signed_in_user(client)
        await graded_attempt(user_id=user.id, score=30)
        await graded_attempt(user_id=user.id, score=90)

        body = (await client.get("/v1/review", params={"max_score": 60})).json()

        assert [item["score"] for item in body["items"]] == [30]

    async def test_filtering_by_missed_concept(self, client: AsyncClient) -> None:
        """A student closing one specific gap across every question that tested it."""
        user = await signed_in_user(client)
        await graded_attempt(user_id=user.id, result_overrides={"concepts_missed": ["net_debt"]})
        await graded_attempt(user_id=user.id, result_overrides={"concepts_missed": ["cash"]})

        body = (await client.get("/v1/review", params={"missed_concept": "net_debt"})).json()

        assert len(body["items"]) == 1
        assert body["items"][0]["concepts_missed"] == ["net_debt"]

    async def test_filtering_by_recency(self, client: AsyncClient) -> None:
        """ "What have I done lately" is a different question from "what did I get wrong"."""
        user = await signed_in_user(client)
        await graded_attempt(user_id=user.id, submitted_at=datetime.now(UTC) - timedelta(days=1))
        await graded_attempt(user_id=user.id, submitted_at=datetime.now(UTC) - timedelta(days=90))

        body = (await client.get("/v1/review", params={"recent_only": True})).json()

        assert len(body["items"]) == 1

    async def test_filtering_by_flagged(self, client: AsyncClient) -> None:
        """A student following up on the grades they disputed."""
        user = await signed_in_user(client)
        flagged = await graded_attempt(user_id=user.id)
        await graded_attempt(user_id=user.id)
        await client.post(f"/v1/attempts/{flagged.id}/flag", json={"reason": "score_too_low"})

        body = (await client.get("/v1/review", params={"flagged_only": True})).json()

        assert len(body["items"]) == 1
        assert body["items"][0]["id"] == str(flagged.id)
        assert body["items"][0]["flagged"] is True

    async def test_filters_combine(self, client: AsyncClient) -> None:
        """Two filters narrow further rather than replacing each other."""
        user = await signed_in_user(client)
        await graded_attempt(user_id=user.id, category_slug="dcf", score=30)
        await graded_attempt(user_id=user.id, category_slug="dcf", score=90)
        await graded_attempt(user_id=user.id, category_slug="valuation", score=30)

        body = (
            await client.get("/v1/review", params={"category_slug": "dcf", "max_score": 60})
        ).json()

        assert len(body["items"]) == 1

    async def test_an_unknown_category_is_rejected(self, client: AsyncClient) -> None:
        """A typo is reported rather than silently returning nothing."""
        await signed_in_user(client)

        response = await client.get("/v1/review", params={"category_slug": "nope"})

        assert response.status_code == 400


class TestReviewPrivacy:
    """History is private to the student who made it."""

    async def test_only_the_callers_own_attempts_are_listed(self, client: AsyncClient) -> None:
        """Another student's evidence never appears in this list."""
        other = await make_user()
        await graded_attempt(user_id=other.id)
        caller = await signed_in_user(client)
        mine = await graded_attempt(user_id=caller.id)

        body = (await client.get("/v1/review")).json()

        assert [item["id"] for item in body["items"]] == [str(mine.id)]

    async def test_review_requires_authentication(self, client: AsyncClient) -> None:
        """No session, no history."""
        response = await client.get("/v1/review")

        assert response.status_code == 401

    async def _diagnostic_attempt(self, user_id, **session_overrides):
        """
        Create a graded attempt inside a diagnostic session.

        Args:
            user_id: Owning user ID.
            **session_overrides: Fields to override on the session, such as its status.

        Returns:
            Attempt: The graded attempt.
        """
        question = await make_question(category_slug="accounting")
        version = await make_question_version(question_id=question.id)
        session_row = await make_session(
            user_id=user_id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
            type=SessionType.DIAGNOSTIC,
            **session_overrides,
        )
        attempt = await make_attempt(
            user_id=user_id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )
        await CRUDAttempt().set_grade_result(attempt_id=attempt.id, result=graded_result())
        return attempt

    async def test_an_unfinished_diagnostic_is_absent_from_review(
        self, client: AsyncClient
    ) -> None:
        """Review is history, and a diagnostic in progress is not history yet.

        The results endpoint answers 409 mid-sitting and the attempt endpoint withholds the
        grade; listing the same scores here would reopen that door and let a student calibrate
        between questions.
        """
        caller = await signed_in_user(client)
        await self._diagnostic_attempt(caller.id)

        body = (await client.get("/v1/review")).json()

        assert body["items"] == []

    async def test_a_finished_diagnostic_appears_in_review(self, client: AsyncClient) -> None:
        """Once the sitting is over its evidence is exactly what review is for."""
        caller = await signed_in_user(client)
        attempt = await self._diagnostic_attempt(
            caller.id, status=SessionStatus.COMPLETED, finished_at=datetime.now(UTC)
        )

        body = (await client.get("/v1/review")).json()

        assert [item["id"] for item in body["items"]] == [str(attempt.id)]

    async def test_practice_is_never_withheld_from_review(self, client: AsyncClient) -> None:
        """The exclusion is scoped to the diagnostic; practice grades are earned as they go."""
        caller = await signed_in_user(client)
        mine = await graded_attempt(user_id=caller.id)

        body = (await client.get("/v1/review")).json()

        assert [item["id"] for item in body["items"]] == [str(mine.id)]


class TestGradeFlags:
    """Disputing a grade."""

    async def test_flagging_a_grade(self, client: AsyncClient) -> None:
        """The straightforward case."""
        user = await signed_in_user(client)
        attempt = await graded_attempt(user_id=user.id)

        response = await client.post(
            f"/v1/attempts/{attempt.id}/flag",
            json={"reason": "score_too_low", "comment": "I covered the net debt bridge."},
        )
        body = response.json()

        assert response.status_code == 201
        assert body["status"] == "open"
        assert body["already_flagged"] is False

    async def test_flagging_twice_returns_the_existing_flag(self, client: AsyncClient) -> None:
        """A flag is a statement, not a vote to be repeated."""
        user = await signed_in_user(client)
        attempt = await graded_attempt(user_id=user.id)
        first = await client.post(f"/v1/attempts/{attempt.id}/flag", json={"reason": "other"})

        second = await client.post(
            f"/v1/attempts/{attempt.id}/flag", json={"reason": "score_too_low"}
        )

        assert second.status_code == 201
        assert second.json()["already_flagged"] is True
        assert second.json()["id"] == first.json()["id"]

    async def test_the_attempt_reports_it_is_flagged(self, client: AsyncClient) -> None:
        """The grade panel must not offer a control the student has already used."""
        user = await signed_in_user(client)
        attempt = await graded_attempt(user_id=user.id)

        before = (await client.get(f"/v1/attempts/{attempt.id}")).json()
        await client.post(f"/v1/attempts/{attempt.id}/flag", json={"reason": "other"})
        after = (await client.get(f"/v1/attempts/{attempt.id}")).json()

        assert before["flagged"] is False
        assert after["flagged"] is True

    async def test_an_ungraded_attempt_cannot_be_flagged(self, client: AsyncClient) -> None:
        """There is nothing to dispute about a grade that does not exist."""
        user = await signed_in_user(client)
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

        response = await client.post(f"/v1/attempts/{attempt.id}/flag", json={"reason": "other"})

        assert response.status_code == 409

    async def test_another_users_attempt_cannot_be_flagged(self, client: AsyncClient) -> None:
        """404 rather than 403, so attempt IDs cannot be probed."""
        other = await make_user()
        attempt = await graded_attempt(user_id=other.id)
        await signed_in_user(client, prefix="intruder")

        response = await client.post(f"/v1/attempts/{attempt.id}/flag", json={"reason": "other"})

        assert response.status_code == 404

    async def test_an_unknown_reason_is_rejected(self, client: AsyncClient) -> None:
        """Only the defined dispute reasons are accepted."""
        user = await signed_in_user(client)
        attempt = await graded_attempt(user_id=user.id)

        response = await client.post(
            f"/v1/attempts/{attempt.id}/flag", json={"reason": "the_model_is_stupid"}
        )

        assert response.status_code == 422

    async def test_flagging_requires_authentication(self, client: AsyncClient) -> None:
        """No session, no dispute."""
        response = await client.post(f"/v1/attempts/{uuid.uuid4()}/flag", json={"reason": "other"})

        assert response.status_code == 401


class TestProgress:
    """Where am I, and am I improving."""

    async def test_every_category_is_reported(self, client: AsyncClient) -> None:
        """A student sees all eight, measured or not."""
        await signed_in_user(client)

        body = (await client.get("/v1/progress")).json()

        assert len(body["categories"]) == 8

    async def test_an_unmeasured_category_is_null_not_zero(self, client: AsyncClient) -> None:
        """ "Not measured" and "measured badly" are different claims.

        Rendering the first as the second would invent a readiness signal the product has no
        basis for, which is the one thing it must never do.
        """
        await signed_in_user(client)

        body = (await client.get("/v1/progress")).json()

        assert all(row["score"] is None for row in body["categories"])
        assert all(row["evidence_count"] == 0 for row in body["categories"])
        assert body["overall"] is None

    async def test_a_measured_category_reports_its_score(self, client: AsyncClient) -> None:
        """Stored mastery, so the progress page agrees with every other surface."""
        user = await signed_in_user(client)
        await CRUDSkillScore().upsert(
            user_id=user.id, category_slug="dcf", score=72, evidence_count=5
        )

        body = (await client.get("/v1/progress")).json()
        dcf = next(row for row in body["categories"] if row["slug"] == "dcf")

        assert dcf["score"] == 72
        assert dcf["evidence_count"] == 5
        assert body["measured_categories"] == 1

    async def test_a_thin_score_is_marked_provisional(self, client: AsyncClient) -> None:
        """A real score from two answers should not be presented as settled."""
        user = await signed_in_user(client)
        await CRUDSkillScore().upsert(
            user_id=user.id, category_slug="dcf", score=72, evidence_count=1
        )

        body = (await client.get("/v1/progress")).json()
        dcf = next(row for row in body["categories"] if row["slug"] == "dcf")

        assert dcf["provisional"] is True

    async def test_weakest_and_strongest_are_named(self, client: AsyncClient) -> None:
        """The two facts a student needs before deciding what to do."""
        user = await signed_in_user(client)
        await CRUDSkillScore().upsert(
            user_id=user.id, category_slug="dcf", score=20, evidence_count=5
        )
        await CRUDSkillScore().upsert(
            user_id=user.id, category_slug="accounting", score=90, evidence_count=5
        )

        body = (await client.get("/v1/progress")).json()

        assert body["weakest"] == "dcf"
        assert body["strongest"] == "accounting"

    async def test_progress_requires_authentication(self, client: AsyncClient) -> None:
        """No session, no progress."""
        response = await client.get("/v1/progress")

        assert response.status_code == 401


class TestMasteryTrend:
    """Reconstructing mastery over time."""

    async def test_no_evidence_produces_no_trend(self) -> None:
        """An empty trend, not a flat line at zero."""
        user = await make_user()

        trend = await MasteryService().trend_for_user(user_id=user.id, now=NOW)

        assert trend == []

    async def test_the_trend_has_one_point_per_week(self) -> None:
        """The window is weekly points ending at the present."""
        user = await make_user()
        await graded_attempt(user_id=user.id, submitted_at=NOW - timedelta(weeks=6))

        trend = await MasteryService().trend_for_user(user_id=user.id, weeks=8, now=NOW)

        assert len(trend) == 8
        assert trend[0]["as_of"] < trend[-1]["as_of"]

    async def test_a_point_ignores_evidence_that_did_not_exist_yet(self) -> None:
        """A trend that knows the future would show every student improving.

        This is the property that makes the reconstruction honest: each point is computed from
        only the attempts that had been graded by that date.
        """
        user = await make_user()
        await graded_attempt(
            user_id=user.id, category_slug="dcf", score=80, submitted_at=NOW - timedelta(days=2)
        )

        trend = await MasteryService().trend_for_user(user_id=user.id, weeks=4, now=NOW)

        assert trend[0]["overall"] is None
        assert trend[-1]["overall"] == 80

    async def test_movement_needs_two_points_to_report(self, client: AsyncClient) -> None:
        """A flat line and no data look identical; only one means the student has not moved."""
        user = await signed_in_user(client)
        await graded_attempt(
            user_id=user.id, score=70, submitted_at=datetime.now(UTC) - timedelta(hours=1)
        )
        await MasteryService().recalculate_for_user(user_id=user.id)

        body = (await client.get("/v1/progress")).json()

        assert body["movement"] is None

    async def test_movement_is_reported_once_there_is_history(self, client: AsyncClient) -> None:
        """Improvement across the window is one number, and it is signed."""
        user = await signed_in_user(client)
        await graded_attempt(
            user_id=user.id,
            category_slug="dcf",
            score=30,
            submitted_at=datetime.now(UTC) - timedelta(weeks=5),
        )
        await graded_attempt(
            user_id=user.id,
            category_slug="dcf",
            score=90,
            submitted_at=datetime.now(UTC) - timedelta(hours=1),
        )
        await MasteryService().recalculate_for_user(user_id=user.id)

        body = (await client.get("/v1/progress")).json()

        assert body["movement"] is not None
        assert body["movement"] > 0
