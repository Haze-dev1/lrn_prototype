"""Billing, entitlements and free-tier enforcement.

The tests that matter most here are not the happy paths. Payment systems fail by granting access
that was not bought, or by losing access that was — so the bulk of this file is duplicate
deliveries, out-of-order deliveries, forged signatures, refunds, and the exact moment a Season
Pass stops working.

Webhook payloads are signed with a real HMAC and posted to the real endpoint. Stubbing the
verification would remove the one control standing between an anonymous POST and paid access,
which is precisely the thing worth testing.
"""

import asyncio
import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from core.config.settings import settings
from core.constants.enums import (
    BillingEventStatus,
    Entitlement,
    EntitlementStatus,
    GradingStatus,
    Plan,
    SessionStatus,
    SessionType,
    SubscriptionStatus,
)
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.billing_crud import CRUDBillingEvent, CRUDEntitlement, CRUDSubscription
from core.cruds.user_crud import CRUDUser
from core.database.database import session
from core.models.billing_model import UserEntitlement
from core.services.billing.entitlement_service import EntitlementService
from core.services.billing.provider import (
    CheckoutLink,
    PaymentProvider,
    ProviderSubscription,
)
from core.services.billing.reconciliation_service import ReconciliationService
from core.services.billing.webhook_service import BillingWebhookService
from tests.conftest import requires_database
from tests.factories import (
    make_attempt,
    make_gradeable_question,
    make_session,
    make_user,
    utc_now,
)

pytestmark = [pytest.mark.asyncio, requires_database]

PASSWORD = "correct-horse-battery-staple"
WEBHOOK_SECRET = "whsec_test_secret_for_the_suite"  # noqa: S105 — a test fixture, not a credential
PRICE_PRO = "price_pro_monthly_test"
PRICE_SEASON = "price_season_pass_test"


# ------------------------------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------------------------------


@pytest.fixture
def stripe_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Configure Stripe credentials for the duration of one test.

    ``conftest`` clears these before anything is imported, so every test that needs billing to be
    "on" opts in explicitly. That keeps the unconfigured behaviour — which is what a fresh clone
    and a misconfigured deployment both get — testable rather than assumed.
    """
    monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_suite")
    monkeypatch.setattr(settings, "STRIPE_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "STRIPE_PRICE_PRO_MONTHLY", PRICE_PRO)
    monkeypatch.setattr(settings, "STRIPE_PRICE_SEASON_PASS", PRICE_SEASON)


async def signed_in_user(client: AsyncClient, *, prefix: str = "student") -> Any:
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


def sign(payload: bytes, *, secret: str = WEBHOOK_SECRET, timestamp: int | None = None) -> str:
    """
    Produce a Stripe-format signature header for a payload.

    Builds the header exactly as Stripe does — ``t=<unix>,v1=<hex hmac>`` over
    ``"<timestamp>.<body>"`` — so the endpoint verifies with the same code path production uses.

    Args:
        payload: Exact bytes that will be sent as the body.
        secret: Signing secret.
        timestamp: Signature timestamp; defaults to now.

    Returns:
        str: Value for the ``Stripe-Signature`` header.
    """
    moment = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{moment}.{payload.decode()}".encode()
    digest = hmac.new(secret.encode(), signed_payload, hashlib.sha256).hexdigest()
    return f"t={moment},v1={digest}"


def build_event(
    event_type: str, obj: dict[str, Any], *, event_id: str | None = None, created: int | None = None
) -> tuple[bytes, dict[str, str]]:
    """
    Build a signed webhook delivery.

    Args:
        event_type: Stripe event type.
        obj: The event's data object.
        event_id: Provider event ID; a fresh one is generated when omitted.
        created: Provider creation time, for out-of-order tests.

    Returns:
        tuple[bytes, dict[str, str]]: Body bytes and headers including the signature.
    """
    payload = {
        "id": event_id or f"evt_{uuid.uuid4().hex[:20]}",
        "type": event_type,
        "created": created if created is not None else int(time.time()),
        "data": {"object": obj},
    }
    body = json.dumps(payload).encode()
    return body, {"stripe-signature": sign(body), "content-type": "application/json"}


def subscription_object(
    *,
    user_id: uuid.UUID,
    subscription_id: str = "sub_test_1",
    customer_id: str = "cus_test_1",
    status: str = "active",
    cancel_at_period_end: bool = False,
    period_end: datetime | None = None,
    price_id: str = PRICE_PRO,
) -> dict[str, Any]:
    """
    Build a Stripe subscription object as a webhook would carry it.

    Args:
        user_id: User the subscription belongs to, carried in metadata.
        subscription_id: Provider subscription ID.
        customer_id: Provider customer ID.
        status: Stripe subscription status.
        cancel_at_period_end: Whether the subscription will not renew.
        period_end: End of the current paid period.
        price_id: Price on the subscription's single item.

    Returns:
        dict[str, Any]: The provider object.
    """
    end = period_end or (datetime.now(UTC) + timedelta(days=30))
    return {
        "id": subscription_id,
        "object": "subscription",
        "customer": customer_id,
        "status": status,
        "cancel_at_period_end": cancel_at_period_end,
        "items": {
            "object": "list",
            "data": [
                {
                    "price": {"id": price_id},
                    "current_period_start": int((end - timedelta(days=30)).timestamp()),
                    "current_period_end": int(end.timestamp()),
                }
            ],
        },
        "metadata": {"user_id": str(user_id), "plan": str(Plan.PRO_MONTHLY)},
    }


def checkout_object(
    *, user_id: uuid.UUID, plan: str = str(Plan.SEASON_PASS), payment_status: str = "paid"
) -> dict[str, Any]:
    """
    Build a completed one-time checkout session object.

    Args:
        user_id: Purchasing user.
        plan: Plan identifier carried in metadata.
        payment_status: Stripe payment status.

    Returns:
        dict[str, Any]: The provider object.
    """
    return {
        "id": f"cs_{uuid.uuid4().hex[:16]}",
        "object": "checkout.session",
        "mode": "payment",
        "payment_status": payment_status,
        "customer": "cus_test_1",
        "client_reference_id": str(user_id),
        "metadata": {"user_id": str(user_id), "plan": plan},
    }


async def grant_pro(user_id: uuid.UUID, *, active_until: datetime | None = None) -> Any:
    """
    Grant paid access directly, standing in for a completed purchase.

    Args:
        user_id: User to grant to.
        active_until: End of the access window, or None for open-ended.

    Returns:
        UserEntitlement: The created grant.
    """
    return await CRUDEntitlement().create(
        obj_in={
            "user_id": user_id,
            "entitlement": Entitlement.PRO,
            "active_from": datetime.now(UTC) - timedelta(minutes=1),
            "active_until": active_until,
            "status": EntitlementStatus.ACTIVE,
            "source_event_id": f"evt_{uuid.uuid4().hex[:16]}",
        }
    )


async def answered_practice_sets(user_id: uuid.UUID, count: int) -> None:
    """
    Create practice sets that each carry an answer, so they count against the allowance.

    Args:
        user_id: Owning user.
        count: How many answered sets to create.
    """
    question, version = await make_gradeable_question()
    for _ in range(count):
        session_row = await make_session(user_id=user_id, type=SessionType.PRACTICE)
        await make_attempt(
            user_id=user_id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )


async def graded_attempts(user_id: uuid.UUID, count: int, *, when: datetime | None = None) -> None:
    """
    Create graded attempts so the daily grading counter sees them.

    ``submitted_at`` is moved with ``graded_at``, because the allowance is counted from
    submission — that is when the spend is committed — and an attempt submitted now but
    backdated only in its grade would be a state the application never produces.

    Args:
        user_id: Owning user.
        count: How many graded attempts to create.
        when: Submission and grading time; defaults to now.
    """
    question, version = await make_gradeable_question()
    graded_at = when or utc_now()
    for _ in range(count):
        session_row = await make_session(user_id=user_id, type=SessionType.PRACTICE)
        await make_attempt(
            user_id=user_id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
            grading_status=GradingStatus.GRADED,
            score=70,
            band="developing",
            submitted_at=graded_at,
            graded_at=graded_at,
        )


class StubProvider(PaymentProvider):
    """A payment provider that records calls instead of contacting Stripe.

    Used only for the two endpoints that create links. It cannot grant anything: every test that
    is about access still goes through the real signature-verified webhook path.
    """

    name = "stripe"

    def __init__(self, *, remote: ProviderSubscription | None = None) -> None:
        """
        Initialise the stub.

        Args:
            remote: Subscription state to return from ``fetch_subscription``.
        """
        self.checkout_calls: list[dict[str, Any]] = []
        self.portal_calls: list[dict[str, Any]] = []
        self.remote = remote

    async def create_checkout_link(self, **kwargs: Any) -> CheckoutLink:
        """Record the call and return a link. See ``PaymentProvider``."""
        self.checkout_calls.append(kwargs)
        return CheckoutLink(session_id="cs_stub", url="https://checkout.example/session")

    async def create_portal_link(self, **kwargs: Any) -> str:
        """Record the call and return a link. See ``PaymentProvider``."""
        self.portal_calls.append(kwargs)
        return "https://portal.example/session"

    def verify_event(self, **kwargs: Any) -> Any:
        """Not used: webhook tests exercise the real verifier. See ``PaymentProvider``."""
        raise NotImplementedError

    async def fetch_subscription(self, *, subscription_id: str) -> ProviderSubscription:
        """Return the configured remote state. See ``PaymentProvider``."""
        assert self.remote is not None
        return self.remote


# ------------------------------------------------------------------------------------------
# Catalogue and entitlement state
# ------------------------------------------------------------------------------------------


class TestPlans:
    """The pricing page's data, which anyone may read."""

    async def test_plans_are_public(self, client: AsyncClient, migrated_database: None) -> None:
        """Pricing is readable without an account; requiring one would be a conversion bug."""
        response = await client.get("/v1/billing/plans")

        assert response.status_code == 200
        body = response.json()
        assert [row["plan"] for row in body["plans"]] == ["free", "pro_monthly", "season_pass"]
        assert body["entitlement"] is None

    async def test_paid_plans_are_unpurchasable_without_configured_prices(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """A plan with no price is shown as unavailable, not offered and then failed at checkout."""
        response = await client.get("/v1/billing/plans")

        body = response.json()
        assert body["billing_enabled"] is False
        paid = [row for row in body["plans"] if row["plan"] != "free"]
        assert all(row["purchasable"] is False for row in paid)

    async def test_configured_plans_are_purchasable(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """With prices configured, both paid plans can be bought."""
        response = await client.get("/v1/billing/plans")

        body = response.json()
        assert body["billing_enabled"] is True
        assert all(row["purchasable"] for row in body["plans"])

    async def test_season_pass_is_marked_one_time_with_a_window(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """The interface needs to tell a one-off purchase from a subscription."""
        body = (await client.get("/v1/billing/plans")).json()

        season = next(row for row in body["plans"] if row["plan"] == "season_pass")
        monthly = next(row for row in body["plans"] if row["plan"] == "pro_monthly")
        assert season["one_time"] is True
        assert season["duration_days"] == settings.SEASON_PASS_DAYS
        assert monthly["one_time"] is False
        assert monthly["duration_days"] is None

    async def test_a_signed_in_caller_sees_their_own_position(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """The page must not try to sell Pro to someone already on it."""
        user = await signed_in_user(client)
        await grant_pro(user.id)

        body = (await client.get("/v1/billing/plans")).json()

        assert body["entitlement"]["is_paid"] is True
        assert body["entitlement"]["plan"] == "pro_monthly"


class TestEntitlements:
    """What the caller is allowed to do, as the API reports it."""

    async def test_requires_authentication(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """Access state is personal; there is no anonymous view of it."""
        assert (await client.get("/v1/entitlements")).status_code == 401

    async def test_a_new_account_is_free_with_a_full_allowance(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """Free is the absence of a grant, and it still permits the whole free tier."""
        await signed_in_user(client)

        body = (await client.get("/v1/entitlements")).json()

        assert body["plan"] == "free"
        assert body["is_paid"] is False
        assert body["active_until"] is None
        assert body["expired_at"] is None
        assert body["can_start_practice"] is True
        assert body["can_grade_answer"] is True
        assert body["can_start_new_diagnostic"] is True
        assert body["usage"]["practice_sessions_used"] == 0
        assert body["usage"]["practice_sessions_remaining"] == settings.FREE_PRACTICE_SESSIONS

    async def test_a_paid_account_reports_paid_access(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """A grant flips every capability regardless of the counters."""
        user = await signed_in_user(client)
        await grant_pro(user.id)

        body = (await client.get("/v1/entitlements")).json()

        assert body["is_paid"] is True
        assert body["can_start_practice"] is True
        assert body["can_grade_answer"] is True
        assert body["can_start_new_diagnostic"] is True

    async def test_an_expired_season_pass_reports_when_it_ended(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """'Your access ended on <date>' is a different message from 'here is what Pro costs'."""
        user = await signed_in_user(client)
        ended = datetime.now(UTC) - timedelta(days=2)
        await CRUDEntitlement().create(
            obj_in={
                "user_id": user.id,
                "entitlement": Entitlement.SEASON_PASS,
                "active_from": ended - timedelta(days=120),
                "active_until": ended,
                "status": EntitlementStatus.ACTIVE,
                "source_event_id": "evt_expired_pass",
            }
        )

        body = (await client.get("/v1/entitlements")).json()

        assert body["is_paid"] is False
        assert body["plan"] == "free"
        assert body["expired_at"] is not None

    async def test_expiry_needs_no_job_to_have_run(self, migrated_database: None) -> None:
        """A window is compared to the clock on every read, so a lapsed pass stops instantly."""
        user = await make_user()
        await CRUDEntitlement().create(
            obj_in={
                "user_id": user.id,
                "entitlement": Entitlement.SEASON_PASS,
                # Still marked ACTIVE: nothing has swept it yet, which is exactly the case that
                # must not grant access.
                "active_from": datetime.now(UTC) - timedelta(days=10),
                "active_until": datetime.now(UTC) - timedelta(seconds=1),
                "status": EntitlementStatus.ACTIVE,
            }
        )

        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None


# ------------------------------------------------------------------------------------------
# Free-tier enforcement
# ------------------------------------------------------------------------------------------


class TestFreeTierLimits:
    """Every limit is the server's decision, and refusing is the server's job."""

    async def test_practice_is_refused_once_the_allowance_is_spent(
        self, client: AsyncClient, migrated_database: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A free account gets a fixed number of practice sets, then a 402 that explains itself."""
        monkeypatch.setattr(settings, "FREE_PRACTICE_SESSIONS", 1)
        user = await signed_in_user(client)
        await answered_practice_sets(user.id, 1)

        response = await client.post("/v1/practice", json={"size": 5, "category_slug": None})

        assert response.status_code == 402
        detail = response.json()["detail"]
        assert detail["reason"] == "practice_limit_reached"
        assert detail["limit"] == 1
        assert detail["upgrade_url"] == "/pricing"

    async def test_the_allowance_is_actually_spendable_through_the_endpoint(
        self, client: AsyncClient, migrated_database: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole limit, exercised the way a student would exercise it.

        Starting a set abandons the previous one, so an allowance counted on sessions rather than
        on answered sets is unspendable: there is only ever one non-abandoned practice session.
        This walks the real endpoint rather than seeding rows, because that is the difference the
        unit-level tests could not see.
        """
        from core.services.questions.seed_service import QuestionSeeder

        monkeypatch.setattr(settings, "FREE_PRACTICE_SESSIONS", 2)
        await QuestionSeeder().run()
        await signed_in_user(client)

        codes = []
        for _ in range(3):
            response = await client.post("/v1/practice", json={"size": 5, "category_slug": None})
            codes.append(response.status_code)
            if response.status_code == 201:
                state = response.json()
                question = state["questions"][0]
                await client.post(
                    f"/v1/sessions/{state['id']}/attempts",
                    json={
                        "question_id": question["id"],
                        "answer": "Enterprise value less net debt gives equity value.",
                    },
                )

        assert codes == [201, 201, 402]

    async def test_paid_access_lifts_the_practice_limit(
        self, client: AsyncClient, migrated_database: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same account, one grant later, is not refused."""
        from core.services.questions.seed_service import QuestionSeeder

        monkeypatch.setattr(settings, "FREE_PRACTICE_SESSIONS", 0)
        await QuestionSeeder().run()
        user = await signed_in_user(client)
        await grant_pro(user.id)

        response = await client.post("/v1/practice", json={"size": 5, "category_slug": None})

        assert response.status_code == 201

    async def test_an_unanswered_set_does_not_spend_the_allowance(
        self, client: AsyncClient, migrated_database: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Changing your mind about set size costs nothing; answering is what costs."""
        monkeypatch.setattr(settings, "FREE_PRACTICE_SESSIONS", 1)
        user = await signed_in_user(client)
        await make_session(
            user_id=user.id,
            type=SessionType.PRACTICE,
            status=SessionStatus.ABANDONED,
            finished_at=utc_now(),
        )
        await make_session(user_id=user.id, type=SessionType.PRACTICE)

        body = (await client.get("/v1/entitlements")).json()

        assert body["usage"]["practice_sessions_used"] == 0
        assert body["can_start_practice"] is True

    async def test_a_set_counts_from_its_first_answer(
        self, client: AsyncClient, migrated_database: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One answer spends the set, however many more the student gives in it."""
        monkeypatch.setattr(settings, "FREE_PRACTICE_SESSIONS", 3)
        user = await signed_in_user(client)
        question, version = await make_gradeable_question()
        session_row = await make_session(user_id=user.id, type=SessionType.PRACTICE)
        await make_attempt(
            user_id=user.id,
            session_id=session_row.id,
            question_id=question.id,
            question_version_id=version.id,
        )

        body = (await client.get("/v1/entitlements")).json()

        assert body["usage"]["practice_sessions_used"] == 1

    async def test_grading_is_refused_once_the_daily_cap_is_reached(
        self, client: AsyncClient, migrated_database: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Each graded answer is a paid model call, so the cap is enforced before the insert."""
        monkeypatch.setattr(settings, "FREE_DAILY_GRADED_ATTEMPTS", 2)
        user = await signed_in_user(client)
        await graded_attempts(user.id, 2)
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            type=SessionType.PRACTICE,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )

        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": "Equity value plus net debt."},
        )

        assert response.status_code == 402
        assert response.json()["detail"]["reason"] == "grading_limit_reached"

    async def test_a_refused_answer_leaves_no_attempt_behind(
        self, client: AsyncClient, migrated_database: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A refusal must not store a half-finished attempt that will never be graded."""
        monkeypatch.setattr(settings, "FREE_DAILY_GRADED_ATTEMPTS", 1)
        user = await signed_in_user(client)
        await graded_attempts(user.id, 1)
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            type=SessionType.PRACTICE,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )

        await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": "Equity value plus net debt."},
        )

        assert (
            await CRUDAttempt().get_for_session_question(
                session_id=session_row.id, question_id=question.id
            )
            is None
        )

    async def test_the_diagnostic_is_never_capped_by_the_grading_limit(
        self, client: AsyncClient, migrated_database: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The free assessment is graded in full, or the results it produces measure nothing."""
        monkeypatch.setattr(settings, "FREE_DAILY_GRADED_ATTEMPTS", 0)
        user = await signed_in_user(client)
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            type=SessionType.DIAGNOSTIC,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )

        response = await client.post(
            f"/v1/sessions/{session_row.id}/attempts",
            json={"question_id": str(question.id), "answer": "Equity value plus net debt."},
        )

        assert response.status_code == 201

    async def test_diagnostic_answers_do_not_spend_the_daily_allowance(
        self, client: AsyncClient, migrated_database: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The diagnostic is exempt from the cap, not merely permitted to exceed it.

        Exempting the check but still counting the answers is the same bug wearing a disguise: a
        24-question sitting fills a 15-answer allowance, and the student who has just been told
        to take that diagnostic is refused every practice answer for the rest of the day, having
        practised nothing. The counter has to agree with the exemption.
        """
        monkeypatch.setattr(settings, "FREE_DAILY_GRADED_ATTEMPTS", 2)
        user = await signed_in_user(client)
        question, version = await make_gradeable_question()
        diagnostic = await make_session(
            user_id=user.id,
            type=SessionType.DIAGNOSTIC,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        # Three graded diagnostic answers against an allowance of two.
        for _ in range(3):
            await make_attempt(
                user_id=user.id,
                session_id=diagnostic.id,
                question_id=(await make_gradeable_question())[0].id,
                question_version_id=version.id,
                grading_status=GradingStatus.GRADED,
                score=70,
                band="developing",
                graded_at=utc_now(),
            )

        entitlements = (await client.get("/v1/entitlements")).json()

        assert entitlements["usage"]["graded_last_24h"] == 0
        assert entitlements["can_grade_answer"] is True

        practice = await make_session(
            user_id=user.id,
            type=SessionType.PRACTICE,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        response = await client.post(
            f"/v1/sessions/{practice.id}/attempts",
            json={"question_id": str(question.id), "answer": "Equity value plus net debt."},
        )

        assert response.status_code == 201

    async def test_concurrent_answers_cannot_outrun_the_allowance(
        self, client: AsyncClient, migrated_database: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The cap is a check followed by a write, so it has to be held under a lock.

        Without one, simultaneous submissions all read the same pre-insert count and all pass:
        twenty answers were accepted against a limit of fifteen, and every one of them is a paid
        model call. This is the test that the serialisation is real rather than incidental.
        """
        monkeypatch.setattr(settings, "FREE_DAILY_GRADED_ATTEMPTS", 3)
        user = await signed_in_user(client)
        slots = []
        for position in range(8):
            question, version = await make_gradeable_question()
            slots.append(
                {
                    "position": position,
                    "question_id": question.id,
                    "question_version_id": version.id,
                }
            )
        practice = await make_session(user_id=user.id, type=SessionType.PRACTICE, questions=slots)

        responses = await asyncio.gather(
            *(
                client.post(
                    f"/v1/sessions/{practice.id}/attempts",
                    json={
                        "question_id": str(slot["question_id"]),
                        "answer": "Equity value plus net debt, less cash and equivalents.",
                    },
                )
                for slot in slots
            )
        )

        accepted = [r for r in responses if r.status_code == 201]
        refused = [r for r in responses if r.status_code == 402]
        assert len(accepted) == 3, f"{len(accepted)} accepted against a limit of 3"
        assert len(refused) == 5
        assert all(r.json()["detail"]["reason"] == "grading_limit_reached" for r in refused)

    async def test_practice_answers_still_spend_the_daily_allowance(
        self, client: AsyncClient, migrated_database: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Excusing the diagnostic must not excuse everything: the cap still has to bite."""
        monkeypatch.setattr(settings, "FREE_DAILY_GRADED_ATTEMPTS", 2)
        user = await signed_in_user(client)
        await graded_attempts(user.id, 2)
        question, version = await make_gradeable_question()
        practice = await make_session(
            user_id=user.id,
            type=SessionType.PRACTICE,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )

        response = await client.post(
            f"/v1/sessions/{practice.id}/attempts",
            json={"question_id": str(question.id), "answer": "Equity value plus net debt."},
        )

        assert response.status_code == 402
        assert response.json()["detail"]["reason"] == "grading_limit_reached"

    async def test_a_duplicate_submission_is_not_refused_by_the_cap(
        self, client: AsyncClient, migrated_database: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A client retry of a stored answer costs nothing and must not be turned into a paywall."""
        monkeypatch.setattr(settings, "FREE_DAILY_GRADED_ATTEMPTS", 1)
        user = await signed_in_user(client)
        question, version = await make_gradeable_question()
        session_row = await make_session(
            user_id=user.id,
            type=SessionType.PRACTICE,
            questions=[
                {"position": 0, "question_id": question.id, "question_version_id": version.id}
            ],
        )
        payload = {"question_id": str(question.id), "answer": "Equity value plus net debt."}
        first = await client.post(f"/v1/sessions/{session_row.id}/attempts", json=payload)
        assert first.status_code == 201
        # The first answer is now graded, which spends the whole allowance.
        await graded_attempts(user.id, 1)

        second = await client.post(f"/v1/sessions/{session_row.id}/attempts", json=payload)

        assert second.status_code == 200
        assert second.json()["duplicate"] is True

    async def test_a_second_diagnostic_needs_a_paid_plan(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """One free measurement. A second one is a paid capability."""
        user = await signed_in_user(client)
        await make_session(
            user_id=user.id,
            type=SessionType.DIAGNOSTIC,
            status=SessionStatus.COMPLETED,
            finished_at=utc_now(),
        )

        response = await client.post("/v1/diagnostic")

        assert response.status_code == 402
        assert response.json()["detail"]["reason"] == "diagnostic_limit_reached"

    async def test_resuming_a_diagnostic_is_never_refused(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """A reload mid-sitting must not hit the paywall that guards starting a new one."""
        from core.services.questions.seed_service import QuestionSeeder

        await QuestionSeeder().run()
        await signed_in_user(client)
        first = await client.post("/v1/diagnostic")
        assert first.status_code == 200

        second = await client.post("/v1/diagnostic")

        assert second.status_code == 200
        assert second.json()["id"] == first.json()["id"]
        assert second.json()["resumed"] is True


# ------------------------------------------------------------------------------------------
# Checkout and portal
# ------------------------------------------------------------------------------------------


class TestCheckout:
    """Starting a purchase. Notably, this cannot grant anything."""

    async def test_checkout_is_unavailable_without_configuration(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """A deployment with no keys says so, rather than failing inside the provider."""
        await signed_in_user(client)

        response = await client.post("/v1/billing/checkout", json={"plan": "pro_monthly"})

        assert response.status_code == 503

    async def test_the_free_plan_cannot_be_purchased(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """Free is the absence of a grant, not something to buy."""
        await signed_in_user(client)

        response = await client.post("/v1/billing/checkout", json={"plan": "free"})

        assert response.status_code == 400

    async def test_an_unknown_plan_is_rejected(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """The plan is validated against the catalogue, not accepted as a string."""
        await signed_in_user(client)

        response = await client.post("/v1/billing/checkout", json={"plan": "enterprise"})

        assert response.status_code == 422

    async def test_checkout_requires_authentication(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """A checkout session is created against an account, so there must be one."""
        assert (
            await client.post("/v1/billing/checkout", json={"plan": "pro_monthly"})
        ).status_code == 401

    async def test_checkout_returns_the_provider_url_and_grants_nothing(
        self,
        client: AsyncClient,
        migrated_database: None,
        stripe_configured: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The critical assertion is the second one: creating a link must not create access."""
        stub = StubProvider()
        monkeypatch.setattr(
            "core.controllers.billing_controller.get_payment_provider", lambda: stub
        )
        user = await signed_in_user(client)

        response = await client.post("/v1/billing/checkout", json={"plan": "season_pass"})

        assert response.status_code == 200
        assert response.json()["url"] == "https://checkout.example/session"
        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None

    async def test_checkout_carries_the_user_and_plan_for_the_webhook(
        self,
        client: AsyncClient,
        migrated_database: None,
        stripe_configured: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Metadata is how an event months later is attributed without a fragile lookup."""
        stub = StubProvider()
        monkeypatch.setattr(
            "core.controllers.billing_controller.get_payment_provider", lambda: stub
        )
        user = await signed_in_user(client)

        await client.post("/v1/billing/checkout", json={"plan": "pro_monthly"})

        call = stub.checkout_calls[0]
        assert call["client_reference_id"] == str(user.id)
        assert call["metadata"] == {"user_id": str(user.id), "plan": "pro_monthly"}
        assert call["price_id"] == PRICE_PRO
        assert call["mode"] == "subscription"

    async def test_an_entitled_user_cannot_buy_a_second_plan(
        self,
        client: AsyncClient,
        migrated_database: None,
        stripe_configured: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Taking money for overlapping access produces a refund conversation, not a customer."""
        stub = StubProvider()
        monkeypatch.setattr(
            "core.controllers.billing_controller.get_payment_provider", lambda: stub
        )
        user = await signed_in_user(client)
        await grant_pro(user.id)

        response = await client.post("/v1/billing/checkout", json={"plan": "pro_monthly"})

        assert response.status_code == 409
        assert stub.checkout_calls == []


class TestPortal:
    """Managing an existing plan, which happens at the provider."""

    async def test_the_portal_needs_a_billing_account(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """There is nothing to open for someone who has never paid."""
        await signed_in_user(client)

        response = await client.post("/v1/billing/portal")

        assert response.status_code == 404

    async def test_the_portal_opens_for_a_known_customer(
        self,
        client: AsyncClient,
        migrated_database: None,
        stripe_configured: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A stored customer ID is what makes the portal reachable."""
        stub = StubProvider()
        monkeypatch.setattr(
            "core.controllers.billing_controller.get_payment_provider", lambda: stub
        )
        user = await signed_in_user(client)
        await CRUDSubscription().upsert_by_provider_id(
            provider_subscription_id="sub_portal",
            obj_in={
                "user_id": user.id,
                "provider_customer_id": "cus_portal",
                "plan": Plan.PRO_MONTHLY,
                "status": SubscriptionStatus.ACTIVE,
            },
        )

        response = await client.post("/v1/billing/portal")

        assert response.status_code == 200
        assert stub.portal_calls[0]["customer_id"] == "cus_portal"


# ------------------------------------------------------------------------------------------
# Webhook: authenticity
# ------------------------------------------------------------------------------------------


class TestWebhookAuthenticity:
    """The signature is the only thing between an anonymous POST and paid access."""

    async def test_an_unsigned_delivery_is_rejected(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """No signature, no event."""
        user = await make_user()
        body, _ = build_event("checkout.session.completed", checkout_object(user_id=user.id))

        response = await client.post("/v1/webhooks/stripe", content=body)

        assert response.status_code == 400
        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None

    async def test_a_forged_signature_is_rejected(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """A signature made with the wrong secret proves nothing."""
        user = await make_user()
        body, _ = build_event("checkout.session.completed", checkout_object(user_id=user.id))
        headers = {"stripe-signature": sign(body, secret="whsec_not_the_real_secret")}

        response = await client.post("/v1/webhooks/stripe", content=body, headers=headers)

        assert response.status_code == 400
        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None

    async def test_a_tampered_payload_is_rejected(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """The signature covers the bytes, so editing the body after signing invalidates it."""
        user = await make_user()
        body, headers = build_event("checkout.session.completed", checkout_object(user_id=user.id))
        tampered = body.replace(b'"payment_status": "paid"', b'"payment_status": "PAID"')

        response = await client.post("/v1/webhooks/stripe", content=tampered, headers=headers)

        assert response.status_code == 400

    async def test_a_stale_signature_is_rejected(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """The timestamp tolerance is what stops a captured payload being replayed forever."""
        user = await make_user()
        body, _ = build_event("checkout.session.completed", checkout_object(user_id=user.id))
        headers = {"stripe-signature": sign(body, timestamp=int(time.time()) - 3600)}

        response = await client.post("/v1/webhooks/stripe", content=body, headers=headers)

        assert response.status_code == 400

    async def test_webhooks_are_refused_when_no_secret_is_configured(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """With no secret there is no way to verify, so there is no way to accept."""
        user = await make_user()
        body, headers = build_event("checkout.session.completed", checkout_object(user_id=user.id))

        response = await client.post("/v1/webhooks/stripe", content=body, headers=headers)

        assert response.status_code == 503
        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None


# ------------------------------------------------------------------------------------------
# Webhook: idempotency and ordering
# ------------------------------------------------------------------------------------------


class TestWebhookIdempotency:
    """Stripe delivers at least once. Duplicates are ordinary traffic, not an anomaly."""

    async def test_a_one_time_purchase_grants_access(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """A paid Season Pass checkout is what creates the grant."""
        user = await make_user()
        body, headers = build_event("checkout.session.completed", checkout_object(user_id=user.id))

        response = await client.post("/v1/webhooks/stripe", content=body, headers=headers)

        assert response.status_code == 200
        grant = await CRUDEntitlement().get_active_for_user(user_id=user.id)
        assert grant is not None
        assert grant.entitlement == Entitlement.SEASON_PASS
        assert grant.active_until is not None

    async def test_a_duplicate_delivery_grants_only_once(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """The whole reason the event log exists: a replayed pass must not become two passes."""
        user = await make_user()
        body, headers = build_event(
            "checkout.session.completed", checkout_object(user_id=user.id), event_id="evt_dup_1"
        )

        first = await client.post("/v1/webhooks/stripe", content=body, headers=headers)
        second = await client.post("/v1/webhooks/stripe", content=body, headers=headers)

        assert first.json()["status"] == "processed"
        assert second.json()["status"] == "duplicate"
        assert second.status_code == 200
        grants = await CRUDEntitlement().get_active_for_user(user_id=user.id)
        assert grants is not None
        event = await CRUDBillingEvent().get_by_provider_id(
            provider="stripe", provider_event_id="evt_dup_1"
        )
        assert event is not None
        assert event.status == BillingEventStatus.PROCESSED

    async def test_an_unsettled_payment_grants_nothing(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """Stripe emits this event before asynchronous payment methods have actually settled."""
        user = await make_user()
        body, headers = build_event(
            "checkout.session.completed",
            checkout_object(user_id=user.id, payment_status="unpaid"),
        )

        await client.post("/v1/webhooks/stripe", content=body, headers=headers)

        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None

    async def test_a_failed_delivery_is_reprocessed_when_the_provider_retries(
        self,
        client: AsyncClient,
        migrated_database: None,
        stripe_configured: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A handler failure returns a 5xx so Stripe retries; the retry must actually run.

        Treating the retry as an ordinary duplicate would strand the event forever, because the
        provider only ever resends the same event ID. This is the difference between a transient
        database blip during a purchase costing a delay and costing a customer their access.
        """
        user = await make_user()
        body, headers = build_event(
            "checkout.session.completed",
            checkout_object(user_id=user.id),
            event_id="evt_transient_1",
        )

        # Fails once, then behaves normally — the shape of a transient failure. `monkeypatch.undo`
        # would also undo the Stripe credentials this test's fixture set, so the handler patches
        # itself out instead.
        original = BillingWebhookService._on_checkout_completed
        calls = {"count": 0}

        async def flaky(self: BillingWebhookService, *, event: Any) -> dict[str, Any]:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("transient database failure")
            return await original(self, event=event)

        monkeypatch.setattr(BillingWebhookService, "_on_checkout_completed", flaky)
        first = await client.post("/v1/webhooks/stripe", content=body, headers=headers)

        assert first.status_code == 500
        record = await CRUDBillingEvent().get_by_provider_id(
            provider="stripe", provider_event_id="evt_transient_1"
        )
        assert record is not None
        assert record.status == BillingEventStatus.FAILED
        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None

        second = await client.post("/v1/webhooks/stripe", content=body, headers=headers)

        assert second.json()["status"] == "processed"
        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is not None

    async def test_a_retry_after_success_still_grants_only_once(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """Reprocessing failures must not weaken the guarantee that a pass is granted once."""
        user = await make_user()
        body, headers = build_event(
            "checkout.session.completed",
            checkout_object(user_id=user.id),
            event_id="evt_once_only",
        )

        for _ in range(3):
            await client.post("/v1/webhooks/stripe", content=body, headers=headers)

        async with session() as db:
            count = await db.execute(
                select(func.count())
                .select_from(UserEntitlement)
                .where(UserEntitlement.user_id == user.id)
            )
            assert count.scalar_one() == 1

    async def test_an_unhandled_event_type_is_recorded_and_ignored(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """The log shows what arrived without the handler pretending to understand it."""
        body, headers = build_event("invoice.upcoming", {"id": "in_1"}, event_id="evt_ignored_1")

        response = await client.post("/v1/webhooks/stripe", content=body, headers=headers)

        assert response.json()["status"] == "ignored"
        event = await CRUDBillingEvent().get_by_provider_id(
            provider="stripe", provider_event_id="evt_ignored_1"
        )
        assert event is not None
        assert event.status == BillingEventStatus.IGNORED

    async def test_an_unattributable_event_grants_nothing(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """Granting access to a guessed account is worse than granting none."""
        body, headers = build_event(
            "checkout.session.completed",
            {
                "id": "cs_orphan",
                "mode": "payment",
                "payment_status": "paid",
                "metadata": {"user_id": str(uuid.uuid4()), "plan": "season_pass"},
            },
        )

        response = await client.post("/v1/webhooks/stripe", content=body, headers=headers)

        assert response.status_code == 200
        async with session() as db:
            granted = await db.execute(select(func.count()).select_from(UserEntitlement))
            assert granted.scalar_one() == 0


class TestSubscriptionLifecycle:
    """Subscribe, cancel, resubscribe — and every out-of-order delivery in between."""

    async def test_an_active_subscription_grants_access(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """The mirror and the grant are written together from one verified event."""
        user = await make_user()
        body, headers = build_event(
            "customer.subscription.created", subscription_object(user_id=user.id)
        )

        await client.post("/v1/webhooks/stripe", content=body, headers=headers)

        grant = await CRUDEntitlement().get_active_for_user(user_id=user.id)
        assert grant is not None
        assert grant.entitlement == Entitlement.PRO
        assert grant.active_until is None
        mirror = await CRUDSubscription().get_by_provider_id(provider_subscription_id="sub_test_1")
        assert mirror is not None
        assert mirror.status == SubscriptionStatus.ACTIVE

    async def test_a_pending_cancellation_keeps_access_until_the_period_ends(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """The student paid through the period; cancelling early would be taking that back."""
        user = await make_user()
        period_end = datetime.now(UTC) + timedelta(days=12)
        created, headers = build_event(
            "customer.subscription.created", subscription_object(user_id=user.id)
        )
        await client.post("/v1/webhooks/stripe", content=created, headers=headers)

        updated, headers = build_event(
            "customer.subscription.updated",
            subscription_object(user_id=user.id, cancel_at_period_end=True, period_end=period_end),
        )
        await client.post("/v1/webhooks/stripe", content=updated, headers=headers)

        grant = await CRUDEntitlement().get_active_for_user(user_id=user.id)
        assert grant is not None
        assert grant.active_until is not None
        assert abs((grant.active_until - period_end).total_seconds()) < 2

    async def test_deletion_revokes_access(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """When the subscription is gone, so is the access it was providing."""
        user = await make_user()
        created, headers = build_event(
            "customer.subscription.created", subscription_object(user_id=user.id)
        )
        await client.post("/v1/webhooks/stripe", content=created, headers=headers)

        deleted, headers = build_event(
            "customer.subscription.deleted",
            subscription_object(user_id=user.id, status="canceled"),
        )
        await client.post("/v1/webhooks/stripe", content=deleted, headers=headers)

        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None
        mirror = await CRUDSubscription().get_by_provider_id(provider_subscription_id="sub_test_1")
        assert mirror is not None
        assert mirror.status == SubscriptionStatus.CANCELED

    async def test_a_failed_payment_does_not_revoke_immediately(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """A declined card that the provider is still retrying is not a cancellation."""
        user = await make_user()
        created, headers = build_event(
            "customer.subscription.created", subscription_object(user_id=user.id)
        )
        await client.post("/v1/webhooks/stripe", content=created, headers=headers)

        past_due, headers = build_event(
            "customer.subscription.updated",
            subscription_object(user_id=user.id, status="past_due"),
        )
        await client.post("/v1/webhooks/stripe", content=past_due, headers=headers)

        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is not None

    async def test_resubscribing_grants_access_again(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """A returning customer gets a fresh grant, not the revoked one back."""
        user = await make_user()
        created, headers = build_event(
            "customer.subscription.created",
            subscription_object(user_id=user.id),
            created=int(time.time()) - 100,
        )
        await client.post("/v1/webhooks/stripe", content=created, headers=headers)
        deleted, headers = build_event(
            "customer.subscription.deleted",
            subscription_object(user_id=user.id, status="canceled"),
            created=int(time.time()) - 50,
        )
        await client.post("/v1/webhooks/stripe", content=deleted, headers=headers)

        again, headers = build_event(
            "customer.subscription.created",
            subscription_object(user_id=user.id, subscription_id="sub_test_2"),
        )
        await client.post("/v1/webhooks/stripe", content=again, headers=headers)

        grant = await CRUDEntitlement().get_active_for_user(user_id=user.id)
        assert grant is not None
        assert grant.status == EntitlementStatus.ACTIVE

    async def test_a_late_delivery_cannot_resurrect_a_cancelled_subscription(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """Stripe does not promise ordering; provider timestamps are what decide precedence."""
        user = await make_user()
        cancelled_at = int(time.time())
        created_at = cancelled_at - 600

        deleted, headers = build_event(
            "customer.subscription.deleted",
            subscription_object(user_id=user.id, status="canceled"),
            created=cancelled_at,
        )
        await client.post("/v1/webhooks/stripe", content=deleted, headers=headers)
        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None

        # The delayed original, redelivered after the cancellation it predates.
        stale, headers = build_event(
            "customer.subscription.updated",
            subscription_object(user_id=user.id, status="active"),
            created=created_at,
        )
        response = await client.post("/v1/webhooks/stripe", content=stale, headers=headers)

        assert response.status_code == 200
        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None
        mirror = await CRUDSubscription().get_by_provider_id(provider_subscription_id="sub_test_1")
        assert mirror is not None
        assert mirror.status == SubscriptionStatus.CANCELED

    async def test_a_delayed_first_delivery_still_grants(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """Access appears when the event lands, however late — and not a moment before."""
        user = await make_user()
        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None

        body, headers = build_event(
            "customer.subscription.created",
            subscription_object(user_id=user.id),
            created=int(time.time()) - 900,
        )
        await client.post("/v1/webhooks/stripe", content=body, headers=headers)

        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is not None


class TestRefunds:
    """A refund takes back what the payment bought — but only when it is a full one."""

    async def test_a_full_refund_revokes_access(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """Money returned, access returned."""
        user = await make_user()
        purchase, headers = build_event(
            "checkout.session.completed", checkout_object(user_id=user.id)
        )
        await client.post("/v1/webhooks/stripe", content=purchase, headers=headers)
        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is not None

        refund, headers = build_event(
            "charge.refunded",
            {
                "id": "ch_1",
                "amount": 9900,
                "amount_refunded": 9900,
                "customer": "cus_test_1",
                "metadata": {"user_id": str(user.id), "plan": str(Plan.SEASON_PASS)},
            },
        )
        await client.post("/v1/webhooks/stripe", content=refund, headers=headers)

        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None

    async def test_a_partial_refund_leaves_access_in_place(
        self, client: AsyncClient, migrated_database: None, stripe_configured: None
    ) -> None:
        """A goodwill credit is not a cancellation of the recruiting season."""
        user = await make_user()
        purchase, headers = build_event(
            "checkout.session.completed", checkout_object(user_id=user.id)
        )
        await client.post("/v1/webhooks/stripe", content=purchase, headers=headers)

        refund, headers = build_event(
            "charge.refunded",
            {
                "id": "ch_2",
                "amount": 9900,
                "amount_refunded": 1000,
                "customer": "cus_test_1",
                "metadata": {"user_id": str(user.id), "plan": str(Plan.SEASON_PASS)},
            },
        )
        await client.post("/v1/webhooks/stripe", content=refund, headers=headers)

        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is not None


# ------------------------------------------------------------------------------------------
# Reconciliation
# ------------------------------------------------------------------------------------------


class TestReconciliation:
    """What repairs the state a webhook never delivered."""

    async def test_elapsed_grants_are_marked_expired(self, migrated_database: None) -> None:
        """Housekeeping, so the table reads honestly. Access never depended on it."""
        user = await make_user()
        await CRUDEntitlement().create(
            obj_in={
                "user_id": user.id,
                "entitlement": Entitlement.SEASON_PASS,
                "active_from": datetime.now(UTC) - timedelta(days=200),
                "active_until": datetime.now(UTC) - timedelta(days=1),
                "status": EntitlementStatus.ACTIVE,
            }
        )

        summary = await ReconciliationService(provider=StubProvider()).run()

        assert summary["expired"] == 1
        latest = await CRUDEntitlement().get_latest_for_user(user_id=user.id)
        assert latest is not None
        assert latest.status == EntitlementStatus.EXPIRED

    async def test_a_missed_cancellation_is_repaired(
        self, migrated_database: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A cancellation whose webhook never arrived would otherwise give away access forever."""
        monkeypatch.setattr(settings, "STRIPE_SECRET_KEY", "sk_test_suite")
        user = await make_user()
        subscription = await CRUDSubscription().upsert_by_provider_id(
            provider_subscription_id="sub_missed",
            obj_in={
                "user_id": user.id,
                "provider_customer_id": "cus_missed",
                "plan": Plan.PRO_MONTHLY,
                "status": SubscriptionStatus.ACTIVE,
            },
        )
        await CRUDEntitlement().create(
            obj_in={
                "user_id": user.id,
                "entitlement": Entitlement.PRO,
                "active_from": datetime.now(UTC) - timedelta(days=3),
                "status": EntitlementStatus.ACTIVE,
                "source_subscription_id": subscription.id,
            }
        )
        stub = StubProvider(
            remote=ProviderSubscription(
                provider_subscription_id="sub_missed",
                provider_customer_id="cus_missed",
                status=SubscriptionStatus.CANCELED,
                price_id=PRICE_PRO,
                current_period_start=None,
                current_period_end=None,
                cancel_at_period_end=False,
            )
        )

        summary = await ReconciliationService(provider=stub).run()

        assert summary["corrected"] == 1
        assert await CRUDEntitlement().get_active_for_user(user_id=user.id) is None

    async def test_reconciliation_does_nothing_without_a_configured_provider(
        self, migrated_database: None
    ) -> None:
        """A deployment without payments must not log a failure every interval."""
        summary = await ReconciliationService(provider=StubProvider()).run()

        assert summary["checked"] == 0
        assert summary["failed"] == 0


class TestAccessStateInternals:
    """The service the endpoints and the gates both read, checked directly."""

    async def test_usage_counts_the_rolling_window_not_the_calendar_day(
        self, migrated_database: None
    ) -> None:
        """A calendar reset would hand two allowances to anyone patient enough to wait for it."""
        user = await make_user()
        await graded_attempts(user.id, 2, when=utc_now() - timedelta(hours=30))
        await graded_attempts(user.id, 1)

        usage = await EntitlementService().usage_for(user=user)

        assert usage.graded_today == 1
