"""Tests for the diagnostic: composition, resuming, completion, and results.

The claims defended here are the ones a student's trust in the result rests on. The composition
is decided by the server and cannot be reshuffled by a client. A refresh resumes rather than
restarts. No rubric leaves the server at any point in the sitting. And a result is never computed
from partial evidence.
"""

import uuid

import pytest
from httpx import AsyncClient

from core.constants.enums import GradingStatus, SessionStatus, SessionType
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.session_crud import CRUDSession
from core.cruds.user_crud import CRUDUser
from core.services.questions.seed_service import QuestionSeeder
from core.services.sessions.composition_service import (
    QUESTIONS_PER_CATEGORY,
    CompositionError,
    DiagnosticComposer,
)
from tests.conftest import requires_database
from tests.factories import graded_result, make_question, make_question_version, make_user

PASSWORD = "correct-horse-battery-staple"
EXPECTED_QUESTIONS = 24

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


async def answer_every_question(client: AsyncClient, state: dict) -> None:
    """
    Submit an answer to every question of a session.

    Args:
        client: HTTP client bound to the application.
        state: The session state payload.
    """
    for question in state["questions"]:
        response = await client.post(
            f"/v1/sessions/{state['id']}/attempts",
            json={
                "question_id": question["id"],
                "answer": "Subtract net debt from enterprise value and add back cash equivalents.",
            },
        )
        assert response.status_code in (200, 201)


async def answer_without_grading(user_id: uuid.UUID, state: dict) -> None:
    """
    Create an ungraded attempt for every question, bypassing the submission endpoint.

    Going through HTTP would queue the background grader, and the fake provider would grade
    everything before the assertion ran. Regressing a graded attempt back to pending is not an
    option either: ``ck_attempts_ungraded_has_no_score`` forbids it at the database level, which
    is exactly the guarantee being relied on elsewhere. Creating the attempts directly is the
    honest way to reach "answered but not yet graded".

    Args:
        user_id: Owning user ID.
        state: The session state payload.
    """
    for question in state["questions"]:
        await CRUDAttempt().create(
            obj_in={
                "session_id": uuid.UUID(state["id"]),
                "user_id": user_id,
                "question_id": uuid.UUID(question["id"]),
                "question_version_id": uuid.UUID(question["question_version_id"]),
                "answer": "An answer awaiting grading.",
                "grading_status": GradingStatus.PENDING,
            }
        )


async def force_grade_all(session_id: uuid.UUID) -> None:
    """
    Mark every attempt in a session graded, bypassing the provider.

    Lets a results test assert on a settled session without depending on background task timing.

    Args:
        session_id: Session whose attempts should be graded.
    """
    for index, attempt in enumerate(await CRUDAttempt().list_for_session(session_id=session_id)):
        # Varied scores so strengths and weaknesses are actually distinguishable.
        await CRUDAttempt().set_grade_result(
            attempt_id=attempt.id, result=graded_result(score=30 + (index * 3) % 70)
        )


class TestComposition:
    """The server decides which 24 questions a student sees."""

    async def test_the_diagnostic_is_twenty_four_questions(self) -> None:
        """Three from each of the eight categories."""
        await QuestionSeeder().run()
        user = await make_user()

        composition, _ = await DiagnosticComposer().compose(user_id=user.id)

        assert len(composition) == EXPECTED_QUESTIONS

    async def test_every_category_contributes_three_questions(self) -> None:
        """A diagnostic missing a category cannot report readiness for it."""
        await QuestionSeeder().run()
        from collections import Counter

        from core.cruds.question_crud import CRUDQuestion

        user = await make_user()
        composition, _ = await DiagnosticComposer().compose(user_id=user.id)

        counts: Counter[str] = Counter()
        for row in composition:
            question = await CRUDQuestion().get_by_id(question_id=row["question_id"])
            assert question is not None
            counts[question.category_slug] += 1

        assert len(counts) == 8
        assert set(counts.values()) == {QUESTIONS_PER_CATEGORY}

    async def test_no_question_appears_twice(self) -> None:
        """A repeated question wastes a slot and double-counts one concept."""
        await QuestionSeeder().run()
        user = await make_user()

        composition, _ = await DiagnosticComposer().compose(user_id=user.id)

        assert len({row["question_id"] for row in composition}) == EXPECTED_QUESTIONS

    async def test_composition_is_deterministic_for_one_student(self) -> None:
        """Composing twice for the same student gives the identical diagnostic.

        A random draw nobody can reproduce is indefensible when a result is disputed.
        """
        await QuestionSeeder().run()
        user = await make_user()

        first, _ = await DiagnosticComposer().compose(user_id=user.id)
        second, _ = await DiagnosticComposer().compose(user_id=user.id)

        assert [row["question_id"] for row in first] == [row["question_id"] for row in second]

    async def test_different_students_get_different_diagnostics(self) -> None:
        """One fixed set of 24 questions would circulate immediately."""
        await QuestionSeeder().run()
        one = await make_user()
        two = await make_user()

        first, _ = await DiagnosticComposer().compose(user_id=one.id)
        second, _ = await DiagnosticComposer().compose(user_id=two.id)

        assert [row["question_id"] for row in first] != [row["question_id"] for row in second]

    async def test_difficulty_rises_across_the_assessment(self) -> None:
        """The ramp runs across the whole sitting, not within each category.

        A student weak in one category learns that early rather than after three hard questions
        in a row, and the sitting reads as one assessment.
        """
        await QuestionSeeder().run()
        from core.cruds.question_crud import CRUDQuestion

        user = await make_user()
        composition, _ = await DiagnosticComposer().compose(user_id=user.id)

        difficulties = []
        for row in composition:
            question = await CRUDQuestion().get_by_id(question_id=row["question_id"])
            assert question is not None
            difficulties.append(question.difficulty)

        first_third = difficulties[:8]
        last_third = difficulties[16:]
        assert sum(last_third) / 8 > sum(first_third) / 8

    async def test_positions_are_sequential_from_zero(self) -> None:
        """The stored order is what the student is served; gaps would break resumption."""
        await QuestionSeeder().run()
        user = await make_user()

        composition, _ = await DiagnosticComposer().compose(user_id=user.id)

        assert [row["position"] for row in composition] == list(range(EXPECTED_QUESTIONS))

    async def test_the_rationale_is_recorded(self) -> None:
        """Why these questions were chosen is captured at selection time."""
        await QuestionSeeder().run()
        user = await make_user()

        _, rationale = await DiagnosticComposer().compose(user_id=user.id)

        assert rationale["strategy"] == "diagnostic_v1"
        assert rationale["questions_per_category"] == QUESTIONS_PER_CATEGORY
        assert rationale["explanation"]

    async def test_a_thin_bank_fails_loudly(self) -> None:
        """A short diagnostic would silently misreport readiness for the thin category."""
        question = await make_question(category_slug="valuation")
        await make_question_version(question_id=question.id)
        user = await make_user()

        with pytest.raises(CompositionError) as caught:
            await DiagnosticComposer().compose(user_id=user.id)

        assert caught.value.shortfalls

    async def test_only_gradeable_questions_are_selected(self) -> None:
        """A draft or unpublished question would guarantee a grading failure."""
        await QuestionSeeder().run()
        from core.cruds.question_crud import CRUDQuestion

        user = await make_user()
        composition, _ = await DiagnosticComposer().compose(user_id=user.id)

        for row in composition:
            question = await CRUDQuestion().get_by_id(question_id=row["question_id"])
            assert question is not None
            assert question.status == "active"


class TestStartingAndResuming:
    """A student must never lose work by reloading."""

    async def test_starting_creates_a_diagnostic_session(self, client: AsyncClient) -> None:
        """The first call composes and stores a full diagnostic."""
        await QuestionSeeder().run()
        await signed_in_user(client)

        response = await client.post("/v1/diagnostic")
        body = response.json()

        assert response.status_code == 200
        assert body["type"] == SessionType.DIAGNOSTIC
        assert body["status"] == SessionStatus.IN_PROGRESS
        assert body["question_count"] == EXPECTED_QUESTIONS
        assert len(body["questions"]) == EXPECTED_QUESTIONS
        assert body["resumed"] is False

    async def test_starting_again_resumes_the_same_session(self, client: AsyncClient) -> None:
        """Reloading returns the same 24 questions, not a fresh set."""
        await QuestionSeeder().run()
        await signed_in_user(client)

        first = (await client.post("/v1/diagnostic")).json()
        second = (await client.post("/v1/diagnostic")).json()

        assert second["id"] == first["id"]
        assert second["resumed"] is True
        assert [q["id"] for q in second["questions"]] == [q["id"] for q in first["questions"]]

    async def test_resuming_preserves_answers_already_given(self, client: AsyncClient) -> None:
        """Answers survive a reload and are reported against their question."""
        await QuestionSeeder().run()
        await signed_in_user(client)
        state = (await client.post("/v1/diagnostic")).json()
        first_question = state["questions"][0]

        await client.post(
            f"/v1/sessions/{state['id']}/attempts",
            json={"question_id": first_question["id"], "answer": "An answer worth keeping."},
        )
        resumed = (await client.post("/v1/diagnostic")).json()

        assert resumed["answered_count"] == 1
        assert resumed["questions"][0]["attempt_id"] is not None

    async def test_a_thin_bank_returns_409_not_a_broken_session(self, client: AsyncClient) -> None:
        """A student is told the product is not ready, rather than given a short diagnostic."""
        await signed_in_user(client)

        response = await client.post("/v1/diagnostic")

        assert response.status_code == 409

    async def test_starting_requires_authentication(self, client: AsyncClient) -> None:
        """No session cookie, no diagnostic."""
        response = await client.post("/v1/diagnostic")

        assert response.status_code == 401


class TestQuestionProtection:
    """No rubric content leaves the server during a sitting."""

    async def test_the_session_payload_carries_no_rubric_content(self, client: AsyncClient) -> None:
        """The whole assessment is served at once and none of it gives away the answers.

        Asserted against the raw response body, not the parsed keys, so a rubric nested anywhere
        inside would still be caught.
        """
        await QuestionSeeder().run()
        await signed_in_user(client)

        response = await client.post("/v1/diagnostic")
        body = response.json()

        for field in ("ideal_answer", "expected_concepts", "common_mistakes", "rubric"):
            assert field not in response.text, f"{field} leaked into the session payload"
        assert all(question["prompt"] for question in body["questions"])

    async def test_a_known_concept_key_does_not_appear(self, client: AsyncClient) -> None:
        """Concept keys are part of the answer key before submission."""
        await QuestionSeeder().run()
        await signed_in_user(client)

        response = await client.post("/v1/diagnostic")

        assert "net_income_links_cfs" not in response.text
        assert "band_thresholds" not in response.text

    async def test_another_users_session_returns_404(self, client: AsyncClient) -> None:
        """404 rather than 403, so session IDs cannot be probed."""
        await QuestionSeeder().run()
        owner = await signed_in_user(client, prefix="owner")
        session_id = (await client.post("/v1/diagnostic")).json()["id"]
        assert owner is not None

        await signed_in_user(client, prefix="intruder")
        response = await client.get(f"/v1/sessions/{session_id}")

        assert response.status_code == 404

    async def test_an_unknown_session_returns_404(self, client: AsyncClient) -> None:
        """A random ID is indistinguishable from someone else's."""
        await signed_in_user(client)

        response = await client.get(f"/v1/sessions/{uuid.uuid4()}")

        assert response.status_code == 404


class TestCompletion:
    """Finishing a diagnostic."""

    async def test_completing_requires_every_question_answered(self, client: AsyncClient) -> None:
        """A diagnostic scored on half the questions reports readiness it never measured."""
        await QuestionSeeder().run()
        await signed_in_user(client)
        state = (await client.post("/v1/diagnostic")).json()
        await client.post(
            f"/v1/sessions/{state['id']}/attempts",
            json={"question_id": state["questions"][0]["id"], "answer": "One answer only."},
        )

        response = await client.post(f"/v1/sessions/{state['id']}/complete")

        assert response.status_code == 409
        assert "24" in response.json()["detail"]

    async def test_completing_a_fully_answered_session_succeeds(self, client: AsyncClient) -> None:
        """The session moves to completed and stamps its finish time."""
        await QuestionSeeder().run()
        await signed_in_user(client)
        state = (await client.post("/v1/diagnostic")).json()
        await answer_every_question(client, state)

        response = await client.post(f"/v1/sessions/{state['id']}/complete")
        body = response.json()

        assert response.status_code == 200
        assert body["status"] == SessionStatus.COMPLETED
        assert body["finished_at"] is not None

    async def test_completing_twice_is_harmless(self, client: AsyncClient) -> None:
        """A duplicate finish click is the same event as one click."""
        await QuestionSeeder().run()
        await signed_in_user(client)
        state = (await client.post("/v1/diagnostic")).json()
        await answer_every_question(client, state)

        first = await client.post(f"/v1/sessions/{state['id']}/complete")
        second = await client.post(f"/v1/sessions/{state['id']}/complete")

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["status"] == SessionStatus.COMPLETED

    async def test_a_completed_session_rejects_further_answers(self, client: AsyncClient) -> None:
        """Reopening a finished diagnostic would let a student improve a recorded result."""
        await QuestionSeeder().run()
        await signed_in_user(client)
        state = (await client.post("/v1/diagnostic")).json()
        await answer_every_question(client, state)
        await client.post(f"/v1/sessions/{state['id']}/complete")

        response = await client.post(
            f"/v1/sessions/{state['id']}/attempts",
            json={"question_id": state["questions"][0]["id"], "answer": "A late change of mind."},
        )

        assert response.status_code == 409

    async def test_completing_another_users_session_returns_404(self, client: AsyncClient) -> None:
        """Ownership is checked before anything else."""
        await QuestionSeeder().run()
        await signed_in_user(client, prefix="owner")
        session_id = (await client.post("/v1/diagnostic")).json()["id"]

        await signed_in_user(client, prefix="intruder")
        response = await client.post(f"/v1/sessions/{session_id}/complete")

        assert response.status_code == 404


class TestResults:
    """What the student is told at the end."""

    async def test_results_are_refused_while_the_session_is_open(self, client: AsyncClient) -> None:
        """An unfinished diagnostic has no result."""
        await QuestionSeeder().run()
        await signed_in_user(client)
        state = (await client.post("/v1/diagnostic")).json()

        response = await client.get(f"/v1/sessions/{state['id']}/results")

        assert response.status_code == 409

    async def test_results_report_progress_while_grading_runs(self, client: AsyncClient) -> None:
        """No scores at all until grading settles.

        A readiness number computed from half the evidence is a wrong number, not an early one.
        """
        await QuestionSeeder().run()
        user = await signed_in_user(client)
        state = (await client.post("/v1/diagnostic")).json()
        await answer_without_grading(user.id, state)
        await client.post(f"/v1/sessions/{state['id']}/complete")

        response = await client.get(f"/v1/sessions/{state['id']}/results")
        body = response.json()

        assert response.status_code == 200
        assert body["progress"]["grading_complete"] is False
        assert body["categories"] == []
        assert body["recommendation"] is None

    async def test_results_report_every_category_once_graded(self, client: AsyncClient) -> None:
        """Eight categories, each with a score backed by this session's evidence."""
        await QuestionSeeder().run()
        await signed_in_user(client)
        state = (await client.post("/v1/diagnostic")).json()
        await answer_every_question(client, state)
        await client.post(f"/v1/sessions/{state['id']}/complete")
        await force_grade_all(uuid.UUID(state["id"]))

        response = await client.get(f"/v1/sessions/{state['id']}/results")
        body = response.json()

        assert response.status_code == 200
        assert body["progress"]["grading_complete"] is True
        assert len(body["categories"]) == 8
        assert all(0 <= row["score"] <= 100 for row in body["categories"])
        assert all(row["answered"] == QUESTIONS_PER_CATEGORY for row in body["categories"])

    async def test_results_name_a_single_next_action(self, client: AsyncClient) -> None:
        """The page exists to answer 'what now', in plain language."""
        await QuestionSeeder().run()
        await signed_in_user(client)
        state = (await client.post("/v1/diagnostic")).json()
        await answer_every_question(client, state)
        await client.post(f"/v1/sessions/{state['id']}/complete")
        await force_grade_all(uuid.UUID(state["id"]))

        body = (await client.get(f"/v1/sessions/{state['id']}/results")).json()
        recommendation = body["recommendation"]

        assert recommendation is not None
        assert recommendation["action"] == "practise_category"
        assert recommendation["category_name"] in recommendation["reason"]
        assert "weakest category" in recommendation["reason"]

    async def test_the_recommendation_targets_the_weakest_category(
        self, client: AsyncClient
    ) -> None:
        """The next action must point at the lowest score, not an arbitrary one."""
        await QuestionSeeder().run()
        await signed_in_user(client)
        state = (await client.post("/v1/diagnostic")).json()
        await answer_every_question(client, state)
        await client.post(f"/v1/sessions/{state['id']}/complete")
        await force_grade_all(uuid.UUID(state["id"]))

        body = (await client.get(f"/v1/sessions/{state['id']}/results")).json()
        weakest = min(body["categories"], key=lambda row: row["score"])

        assert body["recommendation"]["category_slug"] == weakest["slug"]

    async def test_results_carry_no_rubric_content(self, client: AsyncClient) -> None:
        """Missed concept keys are shown; the rubric behind them never is."""
        await QuestionSeeder().run()
        await signed_in_user(client)
        state = (await client.post("/v1/diagnostic")).json()
        await answer_every_question(client, state)
        await client.post(f"/v1/sessions/{state['id']}/complete")
        await force_grade_all(uuid.UUID(state["id"]))

        response = await client.get(f"/v1/sessions/{state['id']}/results")

        assert "ideal_answer" not in response.text
        assert "band_thresholds" not in response.text
        assert "scoring_notes" not in response.text

    async def test_results_are_private_to_their_owner(self, client: AsyncClient) -> None:
        """Another student cannot read a result."""
        await QuestionSeeder().run()
        await signed_in_user(client, prefix="owner")
        state = (await client.post("/v1/diagnostic")).json()
        await answer_every_question(client, state)
        await client.post(f"/v1/sessions/{state['id']}/complete")

        await signed_in_user(client, prefix="intruder")
        response = await client.get(f"/v1/sessions/{state['id']}/results")

        assert response.status_code == 404

    async def test_a_grading_failure_does_not_block_results(self, client: AsyncClient) -> None:
        """One bad model call must not strand a student behind a spinner forever.

        Failures are terminal, so results are shown once nothing is still moving, with the
        failure reported in the progress counts.
        """
        await QuestionSeeder().run()
        user = await signed_in_user(client)
        state = (await client.post("/v1/diagnostic")).json()
        await answer_without_grading(user.id, state)
        await client.post(f"/v1/sessions/{state['id']}/complete")

        # One attempt gives up permanently; the rest grade normally.
        attempts = await CRUDAttempt().list_for_session(session_id=uuid.UUID(state["id"]))
        await CRUDAttempt().set_grading_status(
            attempt_id=attempts[0].id, status=GradingStatus.FAILED
        )
        for index, attempt in enumerate(attempts[1:]):
            await CRUDAttempt().set_grade_result(
                attempt_id=attempt.id, result=graded_result(score=30 + (index * 3) % 70)
            )

        body = (await client.get(f"/v1/sessions/{state['id']}/results")).json()

        assert body["progress"]["grading_complete"] is True
        assert body["progress"]["failed"] == 1
        assert body["categories"]

    async def test_mastery_is_recalculated_from_the_diagnostic(self, client: AsyncClient) -> None:
        """The results page and the dashboard must never disagree about readiness."""
        from core.cruds.skill_score_crud import CRUDSkillScore

        await QuestionSeeder().run()
        user = await signed_in_user(client)
        state = (await client.post("/v1/diagnostic")).json()
        await answer_every_question(client, state)
        await client.post(f"/v1/sessions/{state['id']}/complete")
        await force_grade_all(uuid.UUID(state["id"]))

        body = (await client.get(f"/v1/sessions/{state['id']}/results")).json()
        stored = {
            score.category_slug: score.score
            for score in await CRUDSkillScore().list_for_user(user_id=user.id)
        }

        assert stored
        for row in body["categories"]:
            assert row["score"] == stored[row["slug"]]


class TestSessionIsolation:
    """A diagnostic is one student's, start to finish."""

    async def test_two_students_get_independent_sessions(self, client: AsyncClient) -> None:
        """Starting a diagnostic must not join someone else's."""
        await QuestionSeeder().run()
        await signed_in_user(client, prefix="one")
        first = (await client.post("/v1/diagnostic")).json()

        await signed_in_user(client, prefix="two")
        second = (await client.post("/v1/diagnostic")).json()

        assert first["id"] != second["id"]

    async def test_a_practice_session_is_not_resumed_as_a_diagnostic(self) -> None:
        """Resumption is scoped to the session type, so the two flows cannot cross."""
        await QuestionSeeder().run()
        user = await make_user()
        from tests.factories import make_session

        await make_session(user_id=user.id, type=SessionType.PRACTICE)

        active = await CRUDSession().get_active_for_user(
            user_id=user.id, session_type=SessionType.DIAGNOSTIC
        )

        assert active is None
