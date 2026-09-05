"""Tests for administrative question bank management.

Two things are being defended. First, the admin surface is invisible and unusable to an ordinary
account, because it returns rubric content by design. Second, the lifecycle rules that the
database cannot express hold: no activation without a rubric, no publication of incomplete
content, and no rewriting of a version that has already graded something.
"""

import uuid

import pytest
from httpx import AsyncClient

from core.constants.enums import QuestionStatus, QuestionVersionStatus
from core.cruds.question_crud import CRUDQuestionVersion
from core.cruds.user_crud import CRUDUser
from tests.conftest import requires_database
from tests.factories import make_gradeable_question, make_question, make_question_version

PASSWORD = "correct-horse-battery-staple"

pytestmark = [requires_database, pytest.mark.usefixtures("migrated_database")]

VALID_IDEAL_ANSWER = (
    "Subtract net debt from enterprise value: start with enterprise value, subtract total debt, "
    "add back cash and equivalents, and adjust for preferred stock and minority interest to "
    "reach equity value available to common shareholders."
)


def version_payload(**overrides: object) -> dict[str, object]:
    """
    Build a version payload that passes rubric validation.

    Args:
        **overrides: Fields to override on the valid default.

    Returns:
        dict[str, object]: A publishable version payload.
    """
    payload: dict[str, object] = {
        "prompt": "How do you get from enterprise value to equity value?",
        "ideal_answer": VALID_IDEAL_ANSWER,
        "expected_concepts": [
            {"key": "net_debt", "label": "Net debt adjustment"},
            {"key": "cash", "label": "Treatment of cash"},
            {"key": "preferred", "label": "Preferred stock and minority interest"},
        ],
        "common_mistakes": [{"key": "sign_error", "label": "Reversing the bridge"}],
        "rubric": {"band_thresholds": {"strong": 80, "developing": 55}},
    }
    payload.update(overrides)
    return payload


async def sign_in_as_admin(client: AsyncClient) -> None:
    """
    Register an account, promote it to administrator, and refresh the session.

    Admin rights are read from the database on every request rather than from a token claim, so
    promoting the row is enough; no re-issued token is required.

    Args:
        client: HTTP client bound to the application.
    """
    email = f"admin-{uuid.uuid4().hex[:12]}@example.edu"
    response = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201

    user = await CRUDUser().get_by_email(email=email)
    assert user is not None
    await CRUDUser().update(user_id=user.id, obj_in={"is_admin": True})


async def sign_in_as_student(client: AsyncClient) -> None:
    """
    Register an ordinary account and leave the client signed in as it.

    Args:
        client: HTTP client bound to the application.
    """
    email = f"student-{uuid.uuid4().hex[:12]}@example.edu"
    response = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201


class TestAdminAuthorization:
    """The admin surface must be invisible to an ordinary account."""

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            ("GET", "/v1/admin/questions"),
            ("POST", "/v1/admin/questions"),
            ("GET", "/v1/admin/questions/coverage"),
            ("GET", f"/v1/admin/questions/{uuid.uuid4()}"),
            ("PATCH", f"/v1/admin/questions/{uuid.uuid4()}"),
            ("PUT", f"/v1/admin/questions/{uuid.uuid4()}/status"),
            ("POST", f"/v1/admin/questions/{uuid.uuid4()}/versions"),
            ("GET", f"/v1/admin/questions/{uuid.uuid4()}/versions/{uuid.uuid4()}"),
            ("PATCH", f"/v1/admin/questions/{uuid.uuid4()}/versions/{uuid.uuid4()}"),
            ("POST", f"/v1/admin/questions/{uuid.uuid4()}/versions/{uuid.uuid4()}/publish"),
            ("GET", f"/v1/admin/questions/{uuid.uuid4()}/versions/{uuid.uuid4()}/validation"),
        ],
    )
    async def test_every_admin_route_is_404_for_a_student(
        self, client: AsyncClient, method: str, path: str
    ) -> None:
        """A signed-in non-admin gets 404 everywhere, not 403.

        403 would confirm the endpoint exists. Parameterised over the whole surface so a route
        added later without the dependency fails this test rather than shipping unprotected.
        """
        await sign_in_as_student(client)

        response = await client.request(method, path, json={})

        assert response.status_code == 404
        assert response.json()["detail"] == "Not found"

    async def test_admin_routes_reject_an_unauthenticated_caller(self, client: AsyncClient) -> None:
        """With no session at all the answer is 401, before authorisation is considered."""
        response = await client.get("/v1/admin/questions")

        assert response.status_code == 401

    async def test_admin_can_reach_the_surface(self, client: AsyncClient) -> None:
        """An administrator gets a real response, confirming the 404s above are authorisation."""
        await sign_in_as_admin(client)

        response = await client.get("/v1/admin/questions")

        assert response.status_code == 200


class TestQuestionCreation:
    """Creating questions and their first version."""

    async def test_create_question_without_a_version(self, client: AsyncClient) -> None:
        """A bare question is created in draft with no versions."""
        await sign_in_as_admin(client)

        response = await client.post(
            "/v1/admin/questions",
            json={"category_slug": "valuation", "difficulty": 3, "subcategory": "Comps"},
        )
        body = response.json()

        assert response.status_code == 201
        assert body["status"] == QuestionStatus.DRAFT
        assert body["versions"] == []
        assert body["published_version"] is None

    async def test_create_question_with_an_inline_published_version(
        self, client: AsyncClient
    ) -> None:
        """Authoring a question and its content is one action, not two round trips."""
        await sign_in_as_admin(client)

        response = await client.post(
            "/v1/admin/questions",
            json={
                "category_slug": "valuation",
                "difficulty": 3,
                "initial_version": {**version_payload(), "publish": True},
            },
        )
        body = response.json()

        assert response.status_code == 201
        assert body["version_count"] == 1
        assert body["published_version"]["status"] == QuestionVersionStatus.PUBLISHED

    async def test_question_is_always_created_in_draft(self, client: AsyncClient) -> None:
        """Even with a published version, a new question is not automatically live.

        Activation is a separate, deliberate act: authoring content and putting it in front of
        students are different decisions.
        """
        await sign_in_as_admin(client)

        response = await client.post(
            "/v1/admin/questions",
            json={
                "category_slug": "valuation",
                "difficulty": 3,
                "initial_version": {**version_payload(), "publish": True},
            },
        )

        assert response.json()["status"] == QuestionStatus.DRAFT

    async def test_unknown_category_is_rejected_with_400(self, client: AsyncClient) -> None:
        """A bad category slug names the problem instead of failing on a foreign key."""
        await sign_in_as_admin(client)

        response = await client.post(
            "/v1/admin/questions", json={"category_slug": "not-a-category", "difficulty": 3}
        )

        assert response.status_code == 400
        assert "not-a-category" in response.json()["detail"]

    async def test_difficulty_outside_the_range_is_rejected(self, client: AsyncClient) -> None:
        """Difficulty is bounded at the schema, before it reaches the database constraint."""
        await sign_in_as_admin(client)

        response = await client.post(
            "/v1/admin/questions", json={"category_slug": "valuation", "difficulty": 9}
        )

        assert response.status_code == 422


class TestRubricCompletenessGate:
    """Incomplete content must not enter the graded pool."""

    async def test_publishing_an_incomplete_rubric_is_rejected(self, client: AsyncClient) -> None:
        """Publication fails with the specific reasons, not a constraint violation."""
        await sign_in_as_admin(client)
        question = await make_question(status=QuestionStatus.DRAFT)

        response = await client.post(
            f"/v1/admin/questions/{question.id}/versions",
            json={
                "prompt": "How do you bridge enterprise value to equity value?",
                "ideal_answer": "Subtract debt.",
                "expected_concepts": [],
                "publish": True,
            },
        )
        detail = response.json()["detail"]

        assert response.status_code == 422
        assert detail["is_valid"] is False
        assert len(detail["errors"]) >= 2

    async def test_a_rejected_publish_leaves_no_draft_behind(self, client: AsyncClient) -> None:
        """Validation runs before the insert, so a failed publish creates nothing.

        Otherwise every rejected attempt would leave a stray draft for the author to clean up.
        """
        await sign_in_as_admin(client)
        question = await make_question(status=QuestionStatus.DRAFT)

        await client.post(
            f"/v1/admin/questions/{question.id}/versions",
            json={
                "prompt": "How do you bridge enterprise value to equity value?",
                "ideal_answer": "Subtract debt.",
                "expected_concepts": [],
                "publish": True,
            },
        )

        versions = await CRUDQuestionVersion().list_for_question(question_id=question.id)
        assert versions == []

    async def test_incomplete_content_can_still_be_saved_as_a_draft(
        self, client: AsyncClient
    ) -> None:
        """The gate is on publication, not on saving. Work in progress must be storable."""
        await sign_in_as_admin(client)
        question = await make_question(status=QuestionStatus.DRAFT)

        response = await client.post(
            f"/v1/admin/questions/{question.id}/versions",
            json={
                "prompt": "How do you bridge enterprise value to equity value?",
                "ideal_answer": "Subtract debt.",
                "expected_concepts": [],
                "publish": False,
            },
        )

        assert response.status_code == 201
        assert response.json()["status"] == QuestionVersionStatus.DRAFT

    async def test_validation_endpoint_reports_without_publishing(
        self, client: AsyncClient
    ) -> None:
        """An author can see the verdict before trying to ship, and nothing changes."""
        await sign_in_as_admin(client)
        question = await make_question(status=QuestionStatus.DRAFT)
        created = await client.post(
            f"/v1/admin/questions/{question.id}/versions",
            json={
                "prompt": "How do you bridge enterprise value to equity value?",
                "ideal_answer": "Subtract debt.",
                "expected_concepts": [],
            },
        )
        version_id = created.json()["id"]

        response = await client.get(
            f"/v1/admin/questions/{question.id}/versions/{version_id}/validation"
        )
        body = response.json()

        assert response.status_code == 200
        assert body["is_valid"] is False
        assert body["errors"]

        unchanged = await CRUDQuestionVersion().get_by_id(version_id=uuid.UUID(version_id))
        assert unchanged is not None
        assert unchanged.status == QuestionVersionStatus.DRAFT


class TestVersionImmutability:
    """A version that could have graded an attempt must never be rewritten."""

    async def test_draft_versions_can_be_edited_in_place(self, client: AsyncClient) -> None:
        """A draft has never graded anything, so editing it rewrites no history."""
        await sign_in_as_admin(client)
        question = await make_question(status=QuestionStatus.DRAFT)
        version = await make_question_version(question_id=question.id, published=False)

        response = await client.patch(
            f"/v1/admin/questions/{question.id}/versions/{version.id}",
            json={"prompt": "A corrected prompt with the typo fixed."},
        )

        assert response.status_code == 200
        assert response.json()["prompt"] == "A corrected prompt with the typo fixed."

    async def test_published_versions_cannot_be_edited(self, client: AsyncClient) -> None:
        """Editing a published rubric would change what a past grade meant."""
        await sign_in_as_admin(client)
        question, version = await make_gradeable_question()

        response = await client.patch(
            f"/v1/admin/questions/{question.id}/versions/{version.id}",
            json={"prompt": "Trying to rewrite history."},
        )

        assert response.status_code == 409
        assert "new version" in response.json()["detail"]

    async def test_a_published_version_is_unchanged_after_a_refused_edit(
        self, client: AsyncClient
    ) -> None:
        """The refusal is real, not just a status code: the stored row is untouched."""
        await sign_in_as_admin(client)
        question, version = await make_gradeable_question()
        original_prompt = version.prompt

        await client.patch(
            f"/v1/admin/questions/{question.id}/versions/{version.id}",
            json={"prompt": "Trying to rewrite history."},
        )

        stored = await CRUDQuestionVersion().get_by_id(version_id=version.id)
        assert stored is not None
        assert stored.prompt == original_prompt

    async def test_superseded_versions_cannot_be_edited(self, client: AsyncClient) -> None:
        """A superseded version graded real attempts and stays frozen."""
        await sign_in_as_admin(client)
        question = await make_question()
        first = await make_question_version(question_id=question.id)
        await make_question_version(question_id=question.id)

        response = await client.patch(
            f"/v1/admin/questions/{question.id}/versions/{first.id}",
            json={"prompt": "Trying to rewrite a superseded rubric."},
        )

        assert response.status_code == 409

    async def test_a_version_cannot_be_read_through_another_question(
        self, client: AsyncClient
    ) -> None:
        """The version must belong to the question in the path.

        Looking a version up by ID alone would let a stale or mistyped question ID silently
        return another question's rubric.
        """
        await sign_in_as_admin(client)
        _, version = await make_gradeable_question()
        other_question = await make_question()

        response = await client.get(
            f"/v1/admin/questions/{other_question.id}/versions/{version.id}"
        )

        assert response.status_code == 404


class TestPublishing:
    """Publishing supersedes the previous version and leaves exactly one live rubric."""

    async def test_publishing_supersedes_the_previous_version(self, client: AsyncClient) -> None:
        """The old rubric becomes superseded rather than being deleted or left published."""
        await sign_in_as_admin(client)
        question = await make_question()
        first = await make_question_version(question_id=question.id)
        second = await make_question_version(question_id=question.id, published=False)

        response = await client.post(
            f"/v1/admin/questions/{question.id}/versions/{second.id}/publish"
        )

        assert response.status_code == 200
        assert response.json()["status"] == QuestionVersionStatus.PUBLISHED

        superseded = await CRUDQuestionVersion().get_by_id(version_id=first.id)
        assert superseded is not None
        assert superseded.status == QuestionVersionStatus.SUPERSEDED

    async def test_only_one_version_is_published_at_a_time(self, client: AsyncClient) -> None:
        """Two published versions would make 'which rubric grades this' ambiguous."""
        await sign_in_as_admin(client)
        question = await make_question()
        await make_question_version(question_id=question.id)
        second = await make_question_version(question_id=question.id, published=False)
        await client.post(f"/v1/admin/questions/{question.id}/versions/{second.id}/publish")

        detail = await client.get(f"/v1/admin/questions/{question.id}")
        published = [
            version
            for version in detail.json()["versions"]
            if version["status"] == QuestionVersionStatus.PUBLISHED
        ]

        assert len(published) == 1

    async def test_a_superseded_version_cannot_be_republished(self, client: AsyncClient) -> None:
        """Reinstating an old rubric is refused; a new version must be created from it."""
        await sign_in_as_admin(client)
        question = await make_question()
        first = await make_question_version(question_id=question.id)
        second = await make_question_version(question_id=question.id, published=False)
        await client.post(f"/v1/admin/questions/{question.id}/versions/{second.id}/publish")

        response = await client.post(
            f"/v1/admin/questions/{question.id}/versions/{first.id}/publish"
        )

        assert response.status_code == 409

    async def test_versions_are_numbered_sequentially(self, client: AsyncClient) -> None:
        """Version numbers are assigned server-side and increase."""
        await sign_in_as_admin(client)
        question = await make_question(status=QuestionStatus.DRAFT)

        first = await client.post(
            f"/v1/admin/questions/{question.id}/versions", json=version_payload()
        )
        second = await client.post(
            f"/v1/admin/questions/{question.id}/versions", json=version_payload()
        )

        assert first.json()["version"] == 1
        assert second.json()["version"] == 2

    async def test_the_acting_admin_is_recorded_as_the_author(self, client: AsyncClient) -> None:
        """Every version is traceable to the person who wrote it."""
        await sign_in_as_admin(client)
        question = await make_question(status=QuestionStatus.DRAFT)
        me = await client.get("/v1/auth/me")

        response = await client.post(
            f"/v1/admin/questions/{question.id}/versions", json=version_payload()
        )

        assert response.json()["created_by"] == me.json()["id"]


class TestLifecycle:
    """Activation and retirement."""

    async def test_activation_requires_a_published_version(self, client: AsyncClient) -> None:
        """An active question with no rubric would fail to grade for every student who drew it."""
        await sign_in_as_admin(client)
        question = await make_question(status=QuestionStatus.DRAFT)
        await make_question_version(question_id=question.id, published=False)

        response = await client.put(
            f"/v1/admin/questions/{question.id}/status", json={"status": "active"}
        )

        assert response.status_code == 409
        assert "Publish a version" in response.json()["detail"]

    async def test_a_question_with_a_published_version_can_be_activated(
        self, client: AsyncClient
    ) -> None:
        """The one state that can be served and graded is the one activation allows."""
        await sign_in_as_admin(client)
        question = await make_question(status=QuestionStatus.DRAFT)
        await make_question_version(question_id=question.id)

        response = await client.put(
            f"/v1/admin/questions/{question.id}/status", json={"status": "active"}
        )

        assert response.status_code == 200
        assert response.json()["status"] == QuestionStatus.ACTIVE

    async def test_retirement_is_always_allowed_and_preserves_versions(
        self, client: AsyncClient
    ) -> None:
        """Retiring stops selection without destroying the history behind past grades."""
        await sign_in_as_admin(client)
        question, _ = await make_gradeable_question()

        response = await client.put(
            f"/v1/admin/questions/{question.id}/status", json={"status": "retired"}
        )
        body = response.json()

        assert response.status_code == 200
        assert body["status"] == QuestionStatus.RETIRED
        assert body["version_count"] == 1
        assert body["published_version"] is not None

    async def test_an_unknown_status_is_rejected(self, client: AsyncClient) -> None:
        """Only the defined lifecycle states are accepted."""
        await sign_in_as_admin(client)
        question, _ = await make_gradeable_question()

        response = await client.put(
            f"/v1/admin/questions/{question.id}/status", json={"status": "deleted"}
        )

        assert response.status_code == 422


class TestTaxonomyEditing:
    """Taxonomy is mutable; grading content is not."""

    async def test_category_and_difficulty_can_be_changed(self, client: AsyncClient) -> None:
        """Recategorising changes future weakness attribution, not past grades."""
        await sign_in_as_admin(client)
        question, _ = await make_gradeable_question()

        response = await client.patch(
            f"/v1/admin/questions/{question.id}",
            json={"category_slug": "dcf", "difficulty": 5},
        )
        body = response.json()

        assert response.status_code == 200
        assert body["category_slug"] == "dcf"
        assert body["difficulty"] == 5

    async def test_an_empty_update_is_rejected(self, client: AsyncClient) -> None:
        """A PATCH with no fields is a client error, not a silent no-op."""
        await sign_in_as_admin(client)
        question, _ = await make_gradeable_question()

        response = await client.patch(f"/v1/admin/questions/{question.id}", json={})

        assert response.status_code == 400

    async def test_updating_to_an_unknown_category_is_rejected(self, client: AsyncClient) -> None:
        """The category check applies to edits as well as to creation."""
        await sign_in_as_admin(client)
        question, _ = await make_gradeable_question()

        response = await client.patch(
            f"/v1/admin/questions/{question.id}", json={"category_slug": "not-a-category"}
        )

        assert response.status_code == 400

    async def test_updating_an_unknown_question_is_404(self, client: AsyncClient) -> None:
        """A question that does not exist is not silently created."""
        await sign_in_as_admin(client)

        response = await client.patch(f"/v1/admin/questions/{uuid.uuid4()}", json={"difficulty": 2})

        assert response.status_code == 404


class TestListingAndFilters:
    """The admin list view."""

    async def test_filters_narrow_the_result(self, client: AsyncClient) -> None:
        """Category, status and difficulty filters each apply."""
        await sign_in_as_admin(client)
        await make_question(category_slug="dcf", difficulty=1, status=QuestionStatus.ACTIVE)
        await make_question(category_slug="valuation", difficulty=5, status=QuestionStatus.DRAFT)

        response = await client.get("/v1/admin/questions", params={"category_slug": "dcf"})
        body = response.json()

        assert response.status_code == 200
        assert {item["category_slug"] for item in body["items"]} == {"dcf"}

    async def test_status_filter_applies(self, client: AsyncClient) -> None:
        """Filtering by lifecycle state returns only that state."""
        await sign_in_as_admin(client)
        await make_question(status=QuestionStatus.ACTIVE)
        await make_question(status=QuestionStatus.RETIRED)

        response = await client.get("/v1/admin/questions", params={"status": "retired"})

        assert {item["status"] for item in response.json()["items"]} == {"retired"}

    async def test_search_matches_prompt_text(self, client: AsyncClient) -> None:
        """Searching finds a question by the text of one of its versions."""
        await sign_in_as_admin(client)
        question = await make_question()
        await make_question_version(
            question_id=question.id, prompt="Explain the weighted average cost of capital."
        )

        response = await client.get("/v1/admin/questions", params={"search": "weighted average"})

        assert str(question.id) in {item["id"] for item in response.json()["items"]}

    async def test_an_unknown_category_filter_is_rejected(self, client: AsyncClient) -> None:
        """A typo in a filter is reported rather than silently returning nothing."""
        await sign_in_as_admin(client)

        response = await client.get(
            "/v1/admin/questions", params={"category_slug": "not-a-category"}
        )

        assert response.status_code == 400

    async def test_pagination_returns_a_cursor_and_advances(self, client: AsyncClient) -> None:
        """A full page carries a cursor; following it returns different questions."""
        await sign_in_as_admin(client)
        for _ in range(4):
            await make_question()

        first = await client.get("/v1/admin/questions", params={"limit": 2})
        first_body = first.json()
        assert len(first_body["items"]) == 2
        assert first_body["next_cursor"] is not None

        second = await client.get(
            "/v1/admin/questions", params={"limit": 2, "before": first_body["next_cursor"]}
        )
        second_ids = {item["id"] for item in second.json()["items"]}

        assert second_ids.isdisjoint({item["id"] for item in first_body["items"]})

    async def test_the_final_page_has_no_cursor(self, client: AsyncClient) -> None:
        """An exhausted listing reports null rather than looping forever."""
        await sign_in_as_admin(client)
        await make_question()

        response = await client.get("/v1/admin/questions", params={"limit": 50})

        assert response.json()["next_cursor"] is None

    async def test_the_list_view_carries_no_rubric_content(self, client: AsyncClient) -> None:
        """History listings omit content: rubrics stay out of the most-fetched responses."""
        await sign_in_as_admin(client)
        _, version = await make_gradeable_question()

        response = await client.get("/v1/admin/questions")

        assert version.ideal_answer not in response.text
        assert "ideal_answer" not in response.text


class TestCoverage:
    """Diagnostic readiness reporting."""

    async def test_coverage_reports_a_shortfall_when_the_bank_is_thin(
        self, client: AsyncClient
    ) -> None:
        """An empty bank is not diagnostic-ready and says how many questions are missing."""
        await sign_in_as_admin(client)

        response = await client.get("/v1/admin/questions/coverage")
        body = response.json()

        assert response.status_code == 200
        assert body["diagnostic_ready"] is False
        assert len(body["categories"]) == 8
        assert all(row["shortfall"] == row["required"] for row in body["categories"])

    async def test_coverage_counts_only_gradeable_questions(self, client: AsyncClient) -> None:
        """A draft question, or one with no published rubric, does not count toward readiness."""
        await sign_in_as_admin(client)
        await make_gradeable_question()
        draft = await make_question(status=QuestionStatus.DRAFT)
        await make_question_version(question_id=draft.id)
        unpublished = await make_question(status=QuestionStatus.ACTIVE)
        await make_question_version(question_id=unpublished.id, published=False)

        response = await client.get("/v1/admin/questions/coverage")
        body = response.json()
        valuation = next(row for row in body["categories"] if row["slug"] == "valuation")

        assert valuation["selectable"] == 1
        assert body["total_selectable"] == 1

    async def test_coverage_path_is_not_parsed_as_a_question_id(self, client: AsyncClient) -> None:
        """The literal route wins over the UUID parameter route."""
        await sign_in_as_admin(client)

        response = await client.get("/v1/admin/questions/coverage")

        assert response.status_code == 200
        assert "categories" in response.json()
