"""Tests for answer submission and grade retrieval over HTTP.

Two guarantees are under test. The submission ordering — an answer is durable before grading is
attempted, so no provider failure can lose it — and the response shapes, which must never carry a
score while grading is in flight and must never carry a rubric at all.
"""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from core.constants.enums import GradingStatus, SessionStatus, SessionType
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.session_crud import CRUDSession
from core.cruds.user_crud import CRUDUser
from tests.conftest import requires_database
from tests.factories import graded_result, make_attempt, make_gradeable_question, make_session

PASSWORD = "correct-horse-battery-staple"

pytestmark = [requires_database, pytest.mark.usefixtures("migrated_database")]

ANSWER = "Enterprise value less net debt gives equity value, adding back cash and equivalents."


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


async def open_session(user_id: uuid.UUID):
    """
    Create an in-progress session holding one gradeable question.

    Args:
        user_id: Owning user ID.

    Returns:
        tuple: The session, question and version.
    """
    question, version = await make_gradeable_question()
    session_row = await make_session(
        user_id=user_id,
        questions=[{"position": 0, "question_id": question.id, "question_version_id": version.id}],
    )
    return session_row, question, version


class TestSubmission:
    """Persisting an answer."""

    async def test_an_answer_is_stored_and_returned_immediately(self, client: AsyncClient) -> None:
        """Submission returns as soon as the answer is durable, before grading has run.

        That ordering is the point: the student's work is safe the moment they submit, and a
        provider failure afterwards can only delay a grade.
        """
        user = await signed_in_user(client)
        session_row, question, _ = await open_session(user.id)

        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": ANSWER},
        )
        body = response.json()

        assert response.status_code == 201
        assert body["grading_status"] in {GradingStatus.PENDING, GradingStatus.GRADING}
        assert body["duplicate"] is False

        stored = await CRUDAttempt().get_by_id(attempt_id=uuid.UUID(body["id"]))
        assert stored is not None
        assert stored.answer == ANSWER

    async def test_the_submission_response_carries_no_score(self, client: AsyncClient) -> None:
        """An ungraded attempt has nowhere to put a score, so none can be misread as a zero."""
        user = await signed_in_user(client)
        session_row, question, _ = await open_session(user.id)

        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": ANSWER},
        )
        body = response.json()

        assert "score" not in body
        assert "band" not in body
        assert "feedback" not in body

    async def test_the_version_is_pinned_from_the_session(self, client: AsyncClient) -> None:
        """The answer is graded against the rubric the student was actually shown."""
        user = await signed_in_user(client)
        session_row, question, version = await open_session(user.id)

        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": ANSWER},
        )

        stored = await CRUDAttempt().get_by_id(attempt_id=uuid.UUID(response.json()["id"]))
        assert stored is not None
        assert stored.question_version_id == version.id

    async def test_timing_is_recorded_when_supplied(self, client: AsyncClient) -> None:
        """Client-reported timing is telemetry, stored but never affecting a grade."""
        user = await signed_in_user(client)
        session_row, question, _ = await open_session(user.id)

        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": ANSWER, "time_taken_seconds": 94},
        )

        stored = await CRUDAttempt().get_by_id(attempt_id=uuid.UUID(response.json()["id"]))
        assert stored is not None
        assert stored.time_taken_seconds == 94


class TestIdempotency:
    """A repeated submission must not produce two grades or two paid model calls."""

    async def test_resubmitting_returns_the_original_attempt(self, client: AsyncClient) -> None:
        """A double click and a client retry are the same event to the student."""
        user = await signed_in_user(client)
        session_row, question, _ = await open_session(user.id)
        payload = {"question_id": str(question.id), "answer": ANSWER}

        first = await client.post(f"/v1/sessions/{session_row.id}/attempts", json=payload)
        second = await client.post(f"/v1/sessions/{session_row.id}/attempts", json=payload)

        assert first.status_code == 201
        assert second.status_code == 200
        assert second.json()["duplicate"] is True
        assert second.json()["id"] == first.json()["id"]

    async def test_a_different_answer_does_not_overwrite_the_first(
        self, client: AsyncClient
    ) -> None:
        """The first committed answer stands; a resubmission is not a second chance."""
        user = await signed_in_user(client)
        session_row, question, _ = await open_session(user.id)

        await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": ANSWER},
        )
        await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": "A completely different answer."},
        )

        attempts = await CRUDAttempt().list_for_session(session_id=session_row.id)
        assert len(attempts) == 1
        assert attempts[0].answer == ANSWER


class TestSubmissionAuthorization:
    """An answer can only be submitted to a session the caller owns."""

    async def test_another_users_session_returns_404(self, client: AsyncClient) -> None:
        """404 rather than 403, so session IDs cannot be probed for existence."""
        owner = await signed_in_user(client, prefix="owner")
        session_row, question, _ = await open_session(owner.id)

        await signed_in_user(client, prefix="intruder")
        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": ANSWER},
        )

        assert response.status_code == 404

    async def test_a_question_outside_the_session_returns_404(self, client: AsyncClient) -> None:
        """Owning a session does not grant the right to answer arbitrary questions."""
        user = await signed_in_user(client)
        session_row, _, _ = await open_session(user.id)
        outsider, _ = await make_gradeable_question()

        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(outsider.id), "answer": ANSWER},
        )

        assert response.status_code == 404

    async def test_an_unauthenticated_submission_is_rejected(self, client: AsyncClient) -> None:
        """No session cookie means no submission, regardless of the IDs supplied."""
        user = await signed_in_user(client)
        session_row, question, _ = await open_session(user.id)
        await client.post("/v1/auth/logout")

        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": ANSWER},
        )

        assert response.status_code == 401

    async def test_a_completed_session_rejects_new_answers(self, client: AsyncClient) -> None:
        """A finished session is closed; reopening it would let a student improve a past score."""
        user = await signed_in_user(client)
        session_row, question, _ = await open_session(user.id)
        await CRUDSession().finish(session_id=session_row.id, status=SessionStatus.COMPLETED)

        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": ANSWER},
        )

        assert response.status_code == 409


class TestSubmissionValidation:
    """What the endpoint refuses before anything is stored."""

    async def test_an_empty_answer_is_rejected(self, client: AsyncClient) -> None:
        """Nothing is persisted and no model call is made."""
        user = await signed_in_user(client)
        session_row, question, _ = await open_session(user.id)

        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": ""},
        )

        assert response.status_code == 422

    async def test_a_whitespace_only_answer_is_rejected(self, client: AsyncClient) -> None:
        """Spaces are not an answer, and grading them would spend a paid call to say so."""
        user = await signed_in_user(client)
        session_row, question, _ = await open_session(user.id)

        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": "     \n\t  "},
        )

        assert response.status_code == 422

    async def test_an_oversized_answer_is_rejected(self, client: AsyncClient) -> None:
        """Bounded at the edge so an unbounded payload never reaches a paid model call."""
        user = await signed_in_user(client)
        session_row, question, _ = await open_session(user.id)

        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": "x" * 5000},
        )

        assert response.status_code == 422

    async def test_a_malformed_question_id_is_rejected(self, client: AsyncClient) -> None:
        """A bad identifier is a client error, not a 500."""
        user = await signed_in_user(client)
        session_row, _, _ = await open_session(user.id)

        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": "not-a-uuid", "answer": ANSWER},
        )

        assert response.status_code == 400


class TestGradeRetrieval:
    """Reading an attempt while and after it is graded."""

    async def test_an_ungraded_attempt_reports_only_its_state(self, client: AsyncClient) -> None:
        """The polled response has no score field at all while grading is in flight."""
        user = await signed_in_user(client)
        session_row, question, version = await open_session(user.id)
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )

        response = await client.get(f"/v1/attempts/{attempt.id}")
        body = response.json()

        assert response.status_code == 200
        assert body["grading_status"] == GradingStatus.PENDING
        assert "score" not in body
        assert "feedback" not in body

    async def test_a_graded_attempt_returns_its_evidence(self, client: AsyncClient) -> None:
        """Score, band, concepts and coaching all reach the student."""
        user = await signed_in_user(client)
        session_row, question, version = await open_session(user.id)
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )
        await CRUDAttempt().set_grade_result(attempt_id=attempt.id, result=graded_result())

        response = await client.get(f"/v1/attempts/{attempt.id}")
        body = response.json()

        assert response.status_code == 200
        assert body["score"] == 82
        assert body["band"] == "strong"
        assert body["concepts_hit"] == ["net_debt"]
        assert body["concepts_missed"] == ["cash"]
        assert body["feedback"]

    async def test_a_graded_attempt_reveals_the_ideal_answer(self, client: AsyncClient) -> None:
        """Once an answer is committed the reference becomes teaching material."""
        user = await signed_in_user(client)
        session_row, question, version = await open_session(user.id)
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )
        await CRUDAttempt().set_grade_result(attempt_id=attempt.id, result=graded_result())

        response = await client.get(f"/v1/attempts/{attempt.id}")

        assert response.json()["ideal_answer"] == version.ideal_answer

    async def test_the_rubric_is_never_returned(self, client: AsyncClient) -> None:
        """The reference answer is revealed after submission; the scoring rubric never is.

        A student who could read the rubric could reverse-engineer the grader for every future
        question.
        """
        user = await signed_in_user(client)
        session_row, question, version = await open_session(user.id)
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )
        await CRUDAttempt().set_grade_result(attempt_id=attempt.id, result=graded_result())

        response = await client.get(f"/v1/attempts/{attempt.id}")

        assert "rubric" not in response.text
        assert "expected_concepts" not in response.text
        assert "common_mistakes" not in response.text
        assert "double_count_debt" not in response.text

    async def test_labels_cover_only_the_keys_in_this_grade(self, client: AsyncClient) -> None:
        """Readable concept names are returned for the grade's own keys and no others.

        Returning the full declared list would hand over the question's complete answer key —
        every expected concept and every anticipated mistake, including ones the student never
        triggered. Spaced repetition brings missed questions back, so that would let a student
        memorise the checklist instead of learning the material.
        """
        user = await signed_in_user(client)
        session_row, question, version = await open_session(user.id)
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )
        # The factory's rubric declares a "double_count_debt" mistake this grade does not flag.
        await CRUDAttempt().set_grade_result(attempt_id=attempt.id, result=graded_result())

        body = (await client.get(f"/v1/attempts/{attempt.id}")).json()
        graded_keys = set(body["concepts_hit"] + body["concepts_missed"] + body["mistake_flags"])

        assert set(body["concept_labels"]) == graded_keys
        assert "double_count_debt" not in body["concept_labels"]

    async def test_labels_are_readable(self, client: AsyncClient) -> None:
        """The interface must never have to show a student a raw key like 'net_debt'."""
        user = await signed_in_user(client)
        session_row, question, version = await open_session(user.id)
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )
        await CRUDAttempt().set_grade_result(attempt_id=attempt.id, result=graded_result())

        body = (await client.get(f"/v1/attempts/{attempt.id}")).json()

        assert body["concept_labels"]["net_debt"] == "Net debt adjustment"

    async def test_another_users_attempt_returns_404(self, client: AsyncClient) -> None:
        """Grades are private to the student who earned them."""
        owner = await signed_in_user(client, prefix="owner")
        session_row, question, version = await open_session(owner.id)
        attempt = await make_attempt(
            user_id=owner.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )

        await signed_in_user(client, prefix="intruder")
        response = await client.get(f"/v1/attempts/{attempt.id}")

        assert response.status_code == 404

    async def test_an_unknown_attempt_returns_404(self, client: AsyncClient) -> None:
        """A random ID is indistinguishable from another user's."""
        await signed_in_user(client)

        response = await client.get(f"/v1/attempts/{uuid.uuid4()}")

        assert response.status_code == 404

    async def test_reading_an_attempt_requires_authentication(self, client: AsyncClient) -> None:
        """No session, no grade."""
        user = await signed_in_user(client)
        session_row, question, version = await open_session(user.id)
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )
        await client.post("/v1/auth/logout")

        response = await client.get(f"/v1/attempts/{attempt.id}")

        assert response.status_code == 401


class TestDiagnosticGradeWithholding:
    """The diagnostic reveals nothing until the sitting is over.

    The interface never polls this endpoint during a diagnostic, but that is a client-side
    decision and the server is the authority. A student who called it between questions would
    read their score and the reference answer while still being measured — the exact calibration
    the diagnostic exists to prevent, and it would corrupt every mastery score derived from it.
    """

    async def _diagnostic_attempt(self, user_id: uuid.UUID, **session_overrides):
        """
        Create a graded attempt inside a diagnostic session.

        Args:
            user_id: Owning user ID.
            **session_overrides: Fields to override on the session, such as its status.

        Returns:
            tuple: The attempt and the question version it was graded against.
        """
        question, version = await make_gradeable_question()
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
        return attempt, version

    async def test_an_in_progress_diagnostic_withholds_the_grade(self, client: AsyncClient) -> None:
        """Mid-sitting, a graded diagnostic answer reports state and nothing more."""
        user = await signed_in_user(client)
        attempt, _ = await self._diagnostic_attempt(user.id)

        body = (await client.get(f"/v1/attempts/{attempt.id}")).json()

        assert body["grading_status"] == GradingStatus.GRADED
        for revealed in ("score", "band", "feedback", "ideal_answer", "concepts_missed"):
            assert revealed not in body

    async def test_a_completed_diagnostic_reveals_the_grade(self, client: AsyncClient) -> None:
        """Once the sitting is over the evidence is the whole point of it."""
        user = await signed_in_user(client)
        attempt, version = await self._diagnostic_attempt(
            user.id,
            status=SessionStatus.COMPLETED,
            finished_at=datetime.now(UTC),
        )

        body = (await client.get(f"/v1/attempts/{attempt.id}")).json()

        assert body["score"] == 82
        assert body["ideal_answer"] == version.ideal_answer

    async def test_practice_still_reveals_the_grade_immediately(self, client: AsyncClient) -> None:
        """The gate is scoped to the diagnostic; practice teaches from every answer."""
        user = await signed_in_user(client)
        session_row, question, version = await open_session(user.id)
        attempt = await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )
        await CRUDAttempt().set_grade_result(attempt_id=attempt.id, result=graded_result())

        body = (await client.get(f"/v1/attempts/{attempt.id}")).json()

        assert body["score"] == 82
        assert body["ideal_answer"] == version.ideal_answer
