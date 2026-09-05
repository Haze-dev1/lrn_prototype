"""Tests for onboarding, profile editing, consent, data export, and account deletion."""

import uuid

import pytest
from httpx import AsyncClient

from core.config.settings import settings
from core.cruds.user_crud import CRUDProfile, CRUDUser
from tests.conftest import requires_database
from tests.factories import (
    graded_result,
    make_attempt,
    make_gradeable_question,
    make_session,
)

PASSWORD = "correct-horse-battery-staple"

pytestmark = [requires_database, pytest.mark.usefixtures("migrated_database")]


def unique_email(prefix: str = "student") -> str:
    """
    Build an email address unique to one test.

    Args:
        prefix: Readable prefix for the local part.

    Returns:
        str: A unique email address.
    """
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.edu"


async def signed_in(client: AsyncClient) -> str:
    """
    Register a fresh account and leave the client signed in as it.

    Args:
        client: HTTP client bound to the application.

    Returns:
        str: The registered email address.
    """
    email = unique_email()
    response = await client.post("/v1/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201
    return email


class TestOnboarding:
    """Capturing school, graduation year and target role."""

    async def test_onboarding_saves_answers_and_marks_completion(self, client: AsyncClient) -> None:
        """Completing onboarding records the answers and flips the completion flag."""
        await signed_in(client)

        response = await client.post(
            "/v1/onboarding",
            json={"school": "Example College", "graduation_year": 2028, "target_role": "both"},
        )
        body = response.json()

        assert response.status_code == 200
        assert body["onboarding_complete"] is True
        assert body["profile"]["school"] == "Example College"
        assert body["profile"]["graduation_year"] == 2028
        assert body["profile"]["target_role"] == "both"

    async def test_onboarding_does_not_grant_consent(self, client: AsyncClient) -> None:
        """Recruiting consent is not implied by finishing onboarding."""
        await signed_in(client)

        response = await client.post(
            "/v1/onboarding",
            json={"school": "Example College", "graduation_year": 2028, "target_role": "ib"},
        )

        assert response.json()["profile"]["recruiting_consent"] is False

    async def test_re_submitting_updates_answers_without_resetting_completion(
        self, client: AsyncClient
    ) -> None:
        """Editing onboarding later must not look like the student just onboarded."""
        await signed_in(client)
        first = await client.post(
            "/v1/onboarding",
            json={"school": "First College", "graduation_year": 2027, "target_role": "ib"},
        )
        original_time = first.json()["profile"]["onboarding_completed_at"]

        second = await client.post(
            "/v1/onboarding",
            json={"school": "Second College", "graduation_year": 2028, "target_role": "pe"},
        )

        assert second.json()["profile"]["school"] == "Second College"
        assert second.json()["profile"]["onboarding_completed_at"] == original_time

    async def test_onboarding_requires_authentication(self, client: AsyncClient) -> None:
        """An anonymous caller cannot write a profile."""
        response = await client.post(
            "/v1/onboarding",
            json={"school": "X", "graduation_year": 2028, "target_role": "ib"},
        )

        assert response.status_code == 401

    @pytest.mark.parametrize(
        "payload",
        [
            {"school": "X", "graduation_year": 1200, "target_role": "ib"},
            {"school": "X", "graduation_year": 2028, "target_role": "hedge_fund"},
            {"school": "", "graduation_year": 2028, "target_role": "ib"},
        ],
    )
    async def test_invalid_onboarding_is_rejected(self, client: AsyncClient, payload: dict) -> None:
        """Out-of-range years and unknown roles never reach the database."""
        await signed_in(client)

        assert (await client.post("/v1/onboarding", json=payload)).status_code == 422


class TestRecruitingConsent:
    """Consent is explicit, revocable, auditable, and never bundled."""

    async def test_consent_can_be_granted_and_is_timestamped(self, client: AsyncClient) -> None:
        """Granting consent records when it happened, making it auditable."""
        await signed_in(client)

        response = await client.put(
            "/v1/account/recruiting-consent", json={"recruiting_consent": True}
        )
        profile = response.json()["profile"]

        assert profile["recruiting_consent"] is True
        assert profile["recruiting_consent_updated_at"] is not None

    async def test_consent_can_be_withdrawn(self, client: AsyncClient) -> None:
        """Withdrawing consent is exactly as easy as granting it."""
        await signed_in(client)
        await client.put("/v1/account/recruiting-consent", json={"recruiting_consent": True})

        response = await client.put(
            "/v1/account/recruiting-consent", json={"recruiting_consent": False}
        )

        assert response.json()["profile"]["recruiting_consent"] is False

    async def test_a_profile_update_cannot_smuggle_consent(self, client: AsyncClient) -> None:
        """Consent cannot be changed as a side effect of saving something else."""
        await signed_in(client)

        response = await client.patch(
            "/v1/profile", json={"school": "New College", "recruiting_consent": True}
        )
        profile = response.json()["profile"]

        assert profile["school"] == "New College"
        assert profile["recruiting_consent"] is False

    async def test_consent_requires_authentication(self, client: AsyncClient) -> None:
        """An anonymous caller cannot change anyone's consent."""
        response = await client.put(
            "/v1/account/recruiting-consent", json={"recruiting_consent": True}
        )

        assert response.status_code == 401


class TestProfileUpdate:
    """Partial profile edits."""

    async def test_a_partial_update_leaves_other_fields_alone(self, client: AsyncClient) -> None:
        """Sending one field must not blank out the others."""
        await signed_in(client)
        await client.post(
            "/v1/onboarding",
            json={"school": "Example College", "graduation_year": 2028, "target_role": "both"},
        )

        response = await client.patch("/v1/profile", json={"school": "Another College"})
        profile = response.json()["profile"]

        assert profile["school"] == "Another College"
        assert profile["graduation_year"] == 2028
        assert profile["target_role"] == "both"

    async def test_an_empty_update_is_rejected(self, client: AsyncClient) -> None:
        """A no-op update is a client error, not a silent success."""
        await signed_in(client)

        assert (await client.patch("/v1/profile", json={})).status_code == 400


class TestDataExport:
    """A user can take their own data, and only their own."""

    async def test_the_export_contains_the_users_own_data(self, client: AsyncClient) -> None:
        """The export includes the account, profile, sessions, attempts and scores."""
        email = await signed_in(client)

        response = await client.get("/v1/account/export")
        body = response.json()

        assert response.status_code == 200
        assert body["account"]["email"] == email
        assert set(body) == {
            "exported_at",
            "account",
            "profile",
            "sessions",
            "attempts",
            "skill_scores",
            "grade_flags",
        }

    async def test_the_export_includes_answers_and_grades(self, client: AsyncClient) -> None:
        """A student's own answers and the grades they received are part of their record."""
        email = await signed_in(client)
        user = await CRUDUser().get_by_email(email=email)
        assert user is not None
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
            answer="My answer about the equity value bridge.",
        )
        from core.cruds.attempt_crud import CRUDAttempt

        await CRUDAttempt().set_grade_result(attempt_id=attempt.id, result=graded_result())

        body = (await client.get("/v1/account/export")).json()

        assert len(body["attempts"]) == 1
        assert body["attempts"][0]["answer"] == "My answer about the equity value bridge."
        assert body["attempts"][0]["score"] == 82

    async def test_the_export_leaks_no_rubric_or_credential_data(self, client: AsyncClient) -> None:
        """An export must not become a route around question protection."""
        email = await signed_in(client)
        user = await CRUDUser().get_by_email(email=email)
        assert user is not None
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

        raw = (await client.get("/v1/account/export")).text.lower()

        for forbidden in (
            "ideal_answer",
            "rubric",
            "expected_concepts",
            "password_hash",
            "google_sub",
            "raw_response",
        ):
            assert forbidden not in raw

    async def test_export_requires_authentication(self, client: AsyncClient) -> None:
        """An anonymous caller cannot export anyone's data."""
        assert (await client.get("/v1/account/export")).status_code == 401


class TestAccountDeletion:
    """Deletion is confirmed, authenticated, and real."""

    async def test_deletion_requires_the_exact_confirmation_phrase(
        self, client: AsyncClient
    ) -> None:
        """A near-miss confirmation does not delete the account."""
        await signed_in(client)

        response = await client.post(
            "/v1/account/delete", json={"confirmation": "yes", "password": PASSWORD}
        )

        assert response.status_code == 422

    async def test_deletion_requires_the_current_password(self, client: AsyncClient) -> None:
        """An unlocked browser is not enough to destroy someone's history."""
        await signed_in(client)

        missing = await client.post("/v1/account/delete", json={"confirmation": "DELETE"})
        wrong = await client.post(
            "/v1/account/delete", json={"confirmation": "DELETE", "password": "not-it"}
        )

        assert missing.status_code == 400
        assert wrong.status_code == 401

    async def test_deletion_removes_the_account_and_its_data(self, client: AsyncClient) -> None:
        """The account and everything cascading from it are gone."""
        email = await signed_in(client)
        user = await CRUDUser().get_by_email(email=email)
        assert user is not None

        response = await client.post(
            "/v1/account/delete", json={"confirmation": "DELETE", "password": PASSWORD}
        )

        assert response.status_code == 200
        assert await CRUDUser().get_by_email(email=email) is None
        assert await CRUDProfile().get_by_user_id(user_id=user.id) is None

    async def test_a_deleted_account_cannot_be_used_afterwards(self, client: AsyncClient) -> None:
        """An access token outliving the account does not authenticate."""
        email = await signed_in(client)
        await client.post(
            "/v1/account/delete", json={"confirmation": "DELETE", "password": PASSWORD}
        )

        assert (await client.get("/v1/auth/me")).status_code == 401
        assert (
            await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
        ).status_code == 401

    async def test_deletion_requires_authentication(self, client: AsyncClient) -> None:
        """An anonymous caller cannot delete an account."""
        response = await client.post(
            "/v1/account/delete", json={"confirmation": "DELETE", "password": PASSWORD}
        )

        assert response.status_code == 401


class TestRateLimiting:
    """Abuse control that does not punish an entire campus."""

    async def test_repeated_guesses_against_one_account_are_blocked(
        self, client: AsyncClient
    ) -> None:
        """The per-account bucket stops password guessing."""
        email = await signed_in(client)

        statuses = [
            (
                await client.post(
                    "/v1/auth/login", json={"email": email, "password": "wrong-password"}
                )
            ).status_code
            for _ in range(settings.LOGIN_RATE_LIMIT_PER_ACCOUNT + 3)
        ]

        assert 401 in statuses
        assert statuses[-1] == 429

    async def test_a_different_account_from_the_same_client_still_works(
        self, client: AsyncClient
    ) -> None:
        """
        Locking one account must not lock everyone sharing a campus NAT address.

        This is why the tight limit is per account and the per-IP limit is deliberately loose.
        """
        victim = await signed_in(client)
        for _ in range(settings.LOGIN_RATE_LIMIT_PER_ACCOUNT + 2):
            await client.post(
                "/v1/auth/login", json={"email": victim, "password": "wrong-password"}
            )

        bystander = unique_email("bystander")
        await client.post("/v1/auth/register", json={"email": bystander, "password": PASSWORD})
        response = await client.post(
            "/v1/auth/login", json={"email": bystander, "password": PASSWORD}
        )

        assert response.status_code == 200

    async def test_a_rate_limited_response_says_when_to_retry(self, client: AsyncClient) -> None:
        """A 429 carries Retry-After so a client can back off correctly."""
        email = await signed_in(client)
        response = None
        for _ in range(settings.LOGIN_RATE_LIMIT_PER_ACCOUNT + 3):
            response = await client.post(
                "/v1/auth/login", json={"email": email, "password": "wrong-password"}
            )

        assert response is not None
        assert response.status_code == 429
        assert int(response.headers["retry-after"]) > 0

    async def test_a_successful_sign_in_clears_the_penalty(self, client: AsyncClient) -> None:
        """Mistyping a password a few times then getting it right does not leave a penalty."""
        email = await signed_in(client)
        for _ in range(settings.LOGIN_RATE_LIMIT_PER_ACCOUNT - 2):
            await client.post("/v1/auth/login", json={"email": email, "password": "wrong-password"})

        assert (
            await client.post("/v1/auth/login", json={"email": email, "password": PASSWORD})
        ).status_code == 200
        # The counter was reset, so a fresh run of wrong guesses is available again.
        assert (
            await client.post("/v1/auth/login", json={"email": email, "password": "wrong-password"})
        ).status_code == 401


class TestGoogleSignIn:
    """Google sign-in when it is not configured."""

    async def test_it_reports_unavailable_rather_than_failing_obscurely(
        self, client: AsyncClient
    ) -> None:
        """With no client ID configured the endpoint says so, rather than erroring internally."""
        response = await client.post("/v1/auth/google", json={"id_token": "anything"})

        assert response.status_code == 503

    async def test_an_empty_token_is_rejected_by_validation(self, client: AsyncClient) -> None:
        """The payload is validated before any verification is attempted."""
        assert (await client.post("/v1/auth/google", json={"id_token": ""})).status_code == 422
