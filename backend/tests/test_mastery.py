"""Tests for mastery score calculation.

The pure weighting function is tested without a database, because its behaviour — recency
dominance, the evidence window, the refusal to invent a score — is the part a student would
challenge, and it should be verifiable in isolation.
"""

from datetime import UTC, datetime, timedelta

import pytest

from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.skill_score_crud import CRUDSkillScore
from core.services.mastery.service import (
    EVIDENCE_WINDOW_DAYS,
    RECENCY_HALF_LIFE_DAYS,
    MasteryService,
    calculate_weighted_score,
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

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def days_ago(days: float) -> datetime:
    """
    Return a timestamp the given number of days before the fixed reference time.

    Args:
        days: How many days in the past.

    Returns:
        datetime: The resulting timestamp.
    """
    return NOW - timedelta(days=days)


class TestWeightedScore:
    """The recency-weighted mean, tested as pure logic."""

    def test_no_evidence_yields_none_not_zero(self) -> None:
        """An unmeasured category must not be reported as a score of zero."""
        assert calculate_weighted_score([], now=NOW) is None

    def test_a_single_attempt_scores_itself(self) -> None:
        """One attempt produces its own score regardless of age within the window."""
        assert calculate_weighted_score([(72, days_ago(0))], now=NOW) == 72

    def test_equal_age_attempts_average(self) -> None:
        """Attempts of the same age contribute equally."""
        assert calculate_weighted_score([(60, days_ago(1)), (80, days_ago(1))], now=NOW) == 70

    def test_recent_work_outweighs_old_work(self) -> None:
        """Improvement shows up: a recent strong score beats an old weak one."""
        score = calculate_weighted_score(
            [(30, days_ago(RECENCY_HALF_LIFE_DAYS * 4)), (90, days_ago(0))], now=NOW
        )

        assert score is not None
        assert score > 80

    def test_a_recent_decline_pulls_the_score_down(self) -> None:
        """The score is not a high-water mark; recent weak work lowers it."""
        score = calculate_weighted_score(
            [(90, days_ago(RECENCY_HALF_LIFE_DAYS * 4)), (30, days_ago(0))], now=NOW
        )

        assert score is not None
        assert score < 40

    def test_half_life_weighting_is_as_documented(self) -> None:
        """An attempt one half-life old carries half the weight of a fresh one."""
        score = calculate_weighted_score(
            [(100, days_ago(0)), (0, days_ago(RECENCY_HALF_LIFE_DAYS))], now=NOW
        )

        # Weights 1.0 and 0.5: (100*1 + 0*0.5) / 1.5 = 66.67
        assert score == 67

    def test_evidence_outside_the_window_is_ignored(self) -> None:
        """Stale evidence does not prop up a category the student has abandoned."""
        assert calculate_weighted_score([(95, days_ago(EVIDENCE_WINDOW_DAYS + 1))], now=NOW) is None

    def test_a_mix_of_stale_and_current_evidence_uses_only_the_current(self) -> None:
        """Only in-window attempts contribute."""
        score = calculate_weighted_score(
            [(95, days_ago(EVIDENCE_WINDOW_DAYS + 10)), (40, days_ago(1))], now=NOW
        )

        assert score == 40

    @pytest.mark.parametrize("raw_score", [-20, 150])
    def test_out_of_range_input_cannot_produce_an_invalid_score(self, raw_score: int) -> None:
        """The result is clamped so it can never violate the database's 0-100 constraint."""
        score = calculate_weighted_score([(raw_score, days_ago(0))], now=NOW)

        assert score is not None
        assert 0 <= score <= 100


@requires_database
@pytest.mark.usefixtures("migrated_database")
class TestMasteryPersistence:
    """Recalculation reads real graded evidence and stores real scores."""

    async def _graded_attempt(self, *, user_id, category_slug: str, score: int) -> None:
        """
        Create and grade one attempt in a given category.

        Args:
            user_id: Owning user ID.
            category_slug: Category the question belongs to.
            score: Score to record.
        """
        question = await make_question(category_slug=category_slug)
        version = await make_question_version(question_id=question.id)
        session_row = await make_session(
            user_id=user_id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        attempt = await make_attempt(
            user_id=user_id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )
        await CRUDAttempt().set_grade_result(
            attempt_id=attempt.id, result=graded_result(score=score, band="developing")
        )

    async def test_scores_are_computed_per_category(self) -> None:
        """Each category is scored from its own evidence only."""
        user = await make_user()
        await self._graded_attempt(user_id=user.id, category_slug="valuation", score=50)
        await self._graded_attempt(user_id=user.id, category_slug="dcf", score=90)

        stored = await MasteryService().recalculate_for_user(user_id=user.id)

        by_category = {row.category_slug: row.score for row in stored}
        assert by_category == {"valuation": 50, "dcf": 90}

    async def test_results_are_returned_weakest_first(self) -> None:
        """The weakest category leads, matching how every consuming surface reads them."""
        user = await make_user()
        await self._graded_attempt(user_id=user.id, category_slug="dcf", score=88)
        await self._graded_attempt(user_id=user.id, category_slug="valuation", score=41)
        await self._graded_attempt(user_id=user.id, category_slug="accounting", score=65)

        stored = await MasteryService().recalculate_for_user(user_id=user.id)

        assert [row.category_slug for row in stored] == ["valuation", "accounting", "dcf"]

    async def test_evidence_count_reflects_contributing_attempts(self) -> None:
        """A score records how much evidence backs it."""
        user = await make_user()
        for score in (40, 60, 80):
            await self._graded_attempt(user_id=user.id, category_slug="valuation", score=score)

        stored = await MasteryService().recalculate_for_user(user_id=user.id)

        assert stored[0].evidence_count == 3

    async def test_recalculation_is_idempotent(self) -> None:
        """Running the rollup twice on unchanged evidence produces the same score."""
        user = await make_user()
        await self._graded_attempt(user_id=user.id, category_slug="valuation", score=55)
        service = MasteryService()

        first = await service.recalculate_for_user(user_id=user.id)
        second = await service.recalculate_for_user(user_id=user.id)

        assert first[0].score == second[0].score

    async def test_ungraded_attempts_do_not_contribute(self) -> None:
        """A pending or failed attempt is not evidence and must not move mastery."""
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

        stored = await MasteryService().recalculate_for_user(user_id=user.id)

        assert stored == []

    async def test_a_user_with_no_evidence_gets_no_scores(self) -> None:
        """Mastery is never invented for a user who has not answered anything."""
        user = await make_user()

        assert await MasteryService().recalculate_for_user(user_id=user.id) == []

    async def test_another_users_evidence_is_not_counted(self) -> None:
        """Mastery is scoped strictly to the owning user."""
        user = await make_user()
        other = await make_user()
        await self._graded_attempt(user_id=other.id, category_slug="valuation", score=95)
        await self._graded_attempt(user_id=user.id, category_slug="valuation", score=35)

        stored = await MasteryService().recalculate_for_user(user_id=user.id)

        assert len(stored) == 1
        assert stored[0].score == 35

    async def test_previous_score_is_preserved_across_recalculation(self) -> None:
        """A changed score keeps the prior value so the interface can show movement."""
        user = await make_user()
        await self._graded_attempt(user_id=user.id, category_slug="valuation", score=40)
        await MasteryService().recalculate_for_user(user_id=user.id)

        await self._graded_attempt(user_id=user.id, category_slug="valuation", score=100)
        await MasteryService().recalculate_for_user(user_id=user.id)

        stored = await CRUDSkillScore().get_for_category(user_id=user.id, category_slug="valuation")
        assert stored is not None
        assert stored.previous_score == 40
        assert stored.score > 40

    async def test_the_rollup_only_touches_recently_active_users(self) -> None:
        """Job cost tracks activity, not total registrations."""
        active = await make_user()
        await make_user()  # No activity, must not be recalculated.
        await self._graded_attempt(user_id=active.id, category_slug="valuation", score=70)

        recalculated = await MasteryService().recalculate_recently_active(since_hours=26)

        assert recalculated == 1
