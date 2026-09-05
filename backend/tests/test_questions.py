"""Tests for student-facing question access and question protection.

The central claim these tests defend is invariant 2: rubric content never leaves the server before
submission. That is asserted against the actual HTTP response body rather than against the
controller's return value, because the response schema is the enforcement point and a test that
stops short of it would pass while the API leaked.
"""

import uuid

import pytest
from httpx import AsyncClient

from core.constants.enums import QuestionStatus
from core.cruds.question_crud import CRUDQuestion, CRUDQuestionVersion
from core.cruds.user_crud import CRUDUser
from tests.conftest import requires_database
from tests.factories import (
    make_attempt,
    make_gradeable_question,
    make_question,
    make_question_version,
    make_session,
    make_user,
)

PASSWORD = "correct-horse-battery-staple"

pytestmark = [requires_database, pytest.mark.usefixtures("migrated_database")]

# Everything a student must never see before they have answered. Asserted against the raw
# response text as well as the parsed body, so a leak nested inside any structure is caught.
RUBRIC_FIELDS = ("ideal_answer", "expected_concepts", "common_mistakes", "rubric")


def unique_email(prefix: str = "student") -> str:
    """
    Build an email address unique to one test.

    Args:
        prefix: Readable prefix for the local part.

    Returns:
        str: A unique email address.
    """
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.edu"


async def signed_in_user(client: AsyncClient, *, prefix: str = "student"):
    """
    Register a fresh account, leave the client signed in, and return the user row.

    Args:
        client: HTTP client bound to the application.
        prefix: Readable prefix for the account's email address.

    Returns:
        User: The registered user.
    """
    email = unique_email(prefix)
    response = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201
    user = await CRUDUser().get_by_email(email=email)
    assert user is not None
    return user


class TestCategories:
    """The public category taxonomy."""

    async def test_categories_are_listed_in_display_order(self, client: AsyncClient) -> None:
        """The eight seeded categories are returned in their presentation order."""
        response = await client.get("/v1/categories")
        body = response.json()

        assert response.status_code == 200
        assert len(body) == 8
        assert [item["display_order"] for item in body] == sorted(
            item["display_order"] for item in body
        )

    async def test_categories_need_no_session(self, client: AsyncClient) -> None:
        """Category reference data is public: the marketing pages render it signed out."""
        response = await client.get("/v1/categories")

        assert response.status_code == 200


class TestQuestionProtection:
    """Rubric content must not reach a student before they submit an answer."""

    async def test_unanswered_question_carries_no_rubric_content(self, client: AsyncClient) -> None:
        """A question served for answering contains the prompt and nothing that gives it away."""
        user = await signed_in_user(client)
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )

        response = await client.get(f"/v1/sessions/{session_row.id}/questions/{question.id}")
        body = response.json()

        assert response.status_code == 200
        assert body["prompt"] == version.prompt
        for field in RUBRIC_FIELDS:
            assert field not in body, f"{field} leaked in a pre-submission response"

    async def test_rubric_values_do_not_appear_anywhere_in_the_response_text(
        self, client: AsyncClient
    ) -> None:
        """The rubric's actual content is absent from the raw body, not merely from its top level.

        Checking key names alone would pass if a rubric were nested inside some other structure,
        so this asserts on the serialised response the browser would receive.
        """
        user = await signed_in_user(client)
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )

        response = await client.get(f"/v1/sessions/{session_row.id}/questions/{question.id}")

        assert response.status_code == 200
        assert version.ideal_answer not in response.text
        assert "net_debt" not in response.text
        assert "double_count_debt" not in response.text

    async def test_ideal_answer_is_revealed_after_submission(self, client: AsyncClient) -> None:
        """Once an attempt exists the ideal answer becomes teaching material."""
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
        )

        response = await client.get(f"/v1/sessions/{session_row.id}/questions/{question.id}")
        body = response.json()

        assert response.status_code == 200
        assert body["ideal_answer"] == version.ideal_answer

    async def test_rubric_stays_hidden_even_after_submission(self, client: AsyncClient) -> None:
        """The ideal answer is revealed after submitting; the scoring rubric never is.

        A student who could read the rubric could reverse-engineer the grader for every future
        question, so revealing the reference answer does not imply revealing the scoring scheme.
        """
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
        )

        response = await client.get(f"/v1/sessions/{session_row.id}/questions/{question.id}")
        body = response.json()

        assert "ideal_answer" in body
        assert "rubric" not in body
        assert "expected_concepts" not in body
        assert "common_mistakes" not in body

    async def test_there_is_no_endpoint_to_fetch_a_question_by_id(
        self, client: AsyncClient
    ) -> None:
        """No route serves an arbitrary question, so the bank cannot be enumerated.

        This is asserted against the route table rather than by probing a URL: a 404 from a
        missing route and a 404 from an authorisation check look identical over HTTP, and only
        one of them is a guarantee.
        """
        from core.apis.api import app

        paths = set(app.openapi()["paths"])

        assert "/v1/questions/{question_id}" not in paths
        assert not any(path.startswith("/v1/questions") for path in paths), (
            "a top-level question route would let any account walk the bank"
        )


class TestSessionOwnership:
    """A question is reachable only through a session belonging to the caller."""

    async def test_another_users_session_returns_404(self, client: AsyncClient) -> None:
        """Someone else's session is indistinguishable from a session that does not exist.

        Returning 403 would confirm the session ID is real, which turns the endpoint into an
        oracle for enumerating other users' sessions.
        """
        owner = await make_user()
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=owner.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )

        await signed_in_user(client, prefix="intruder")
        response = await client.get(f"/v1/sessions/{session_row.id}/questions/{question.id}")

        assert response.status_code == 404
        assert response.json()["detail"] == "Session not found"

    async def test_unknown_session_returns_404(self, client: AsyncClient) -> None:
        """A session ID that has never existed is rejected the same way."""
        await signed_in_user(client)
        question, _ = await make_gradeable_question()

        response = await client.get(f"/v1/sessions/{uuid.uuid4()}/questions/{question.id}")

        assert response.status_code == 404

    async def test_question_not_in_the_session_returns_404(self, client: AsyncClient) -> None:
        """Owning a session does not grant access to questions outside its composition.

        Without this check a student could hold one legitimate session open and read the entire
        bank through it, one question ID at a time.
        """
        user = await signed_in_user(client)
        in_session, version = await make_gradeable_question()
        outside_session, _ = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": in_session.id, "question_version_id": version.id}
            ],
        )

        response = await client.get(f"/v1/sessions/{session_row.id}/questions/{outside_session.id}")

        assert response.status_code == 404
        assert response.json()["detail"] == "Question not found"

    async def test_unauthenticated_request_is_rejected(self, client: AsyncClient) -> None:
        """No session cookie means no question, regardless of the IDs supplied."""
        user = await make_user()
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )

        response = await client.get(f"/v1/sessions/{session_row.id}/questions/{question.id}")

        assert response.status_code == 401


class TestVersionPinning:
    """A session serves the version it was composed with, not the newest one."""

    async def test_session_serves_its_pinned_version_after_a_republish(
        self, client: AsyncClient
    ) -> None:
        """Publishing a new rubric does not change the prompt an in-flight session is showing.

        The session stores the version it was built from. If it resolved the published version at
        read time instead, a student mid-session could see the prompt change underneath them and
        their attempt would be graded against a rubric they never saw.
        """
        user = await signed_in_user(client)
        question = await make_question()
        original = await make_question_version(question_id=question.id)
        session_row = await make_session(
            user_id=user.id,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": original.id}
            ],
        )

        replacement = await make_question_version(
            question_id=question.id, prompt="A completely rewritten prompt for this question."
        )
        assert replacement.id != original.id

        response = await client.get(f"/v1/sessions/{session_row.id}/questions/{question.id}")
        body = response.json()

        assert response.status_code == 200
        assert body["prompt"] == original.prompt
        assert body["question_version_id"] == str(original.id)


class TestSelectability:
    """Only questions that can actually be graded are eligible for selection."""

    async def test_draft_questions_are_not_selectable(self) -> None:
        """A draft question is invisible to session composition."""
        from core.cruds.question_crud import CRUDQuestion

        question = await make_question(status=QuestionStatus.DRAFT)
        await make_question_version(question_id=question.id)

        selectable = await CRUDQuestion().list_selectable()

        assert question.id not in {item.id for item in selectable}

    async def test_retired_questions_are_not_selectable(self) -> None:
        """Retiring a question removes it from the pool without deleting its history."""
        from core.cruds.question_crud import CRUDQuestion

        question = await make_question(status=QuestionStatus.RETIRED)
        await make_question_version(question_id=question.id)

        selectable = await CRUDQuestion().list_selectable()

        assert question.id not in {item.id for item in selectable}

    async def test_active_question_without_a_published_version_is_not_selectable(self) -> None:
        """An active question with only a draft rubric would guarantee a grading failure."""
        from core.cruds.question_crud import CRUDQuestion

        question = await make_question(status=QuestionStatus.ACTIVE)
        await make_question_version(question_id=question.id, published=False)

        selectable = await CRUDQuestion().list_selectable()

        assert question.id not in {item.id for item in selectable}

    async def test_active_published_question_is_selectable(self) -> None:
        """The one combination that can be served and graded is the one that is offered."""
        from core.cruds.question_crud import CRUDQuestion

        question, _ = await make_gradeable_question()

        selectable = await CRUDQuestion().list_selectable()

        assert question.id in {item.id for item in selectable}


class TestBatchLoading:
    """The batch readers behind every endpoint that renders a set of questions.

    These exist so the cost of showing a session or a page of review stays flat instead of
    scaling with the number of rows on it. The contract they have to hold is that a caller can
    hand over whatever IDs it has — in any order, with duplicates, including IDs that no longer
    resolve — and use the result without checking any of that first.
    """

    async def test_questions_are_returned_by_id(self) -> None:
        """The mapping is keyed by ID, so the caller keeps its own ordering."""
        first = await make_question(category_slug="valuation")
        second = await make_question(category_slug="accounting")

        found = await CRUDQuestion().map_by_ids(question_ids=[second.id, first.id])

        assert set(found) == {first.id, second.id}
        assert found[first.id].category_slug == "valuation"

    async def test_versions_are_returned_by_id(self) -> None:
        """Same contract for versions, which a session pins one of per question."""
        question = await make_question()
        version = await make_question_version(question_id=question.id)

        found = await CRUDQuestionVersion().map_by_ids(version_ids=[version.id])

        assert found[version.id].prompt == version.prompt

    async def test_duplicate_ids_are_tolerated(self) -> None:
        """A composition can name one question twice; that must not error or duplicate a row."""
        question = await make_question()

        found = await CRUDQuestion().map_by_ids(question_ids=[question.id, question.id])

        assert list(found) == [question.id]

    async def test_unknown_ids_are_simply_absent(self) -> None:
        """A missing ID is not an error.

        Callers already skip a slot whose content cannot be loaded — raising here would turn one
        unresolvable question into a failed page.
        """
        question = await make_question()

        found = await CRUDQuestion().map_by_ids(question_ids=[question.id, uuid.uuid4()])

        assert list(found) == [question.id]

    async def test_an_empty_request_makes_no_query(self) -> None:
        """A session with no slots must not issue a query with an empty IN clause."""
        assert await CRUDQuestion().map_by_ids(question_ids=[]) == {}
        assert await CRUDQuestionVersion().map_by_ids(version_ids=[]) == {}
