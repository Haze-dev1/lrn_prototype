"""Email: who gets what, exactly once, and how they stop it.

Three things carry the weight here. Every message must be sendable only once — a duplicate
results email is the kind of bug students notice and remember. Every lifecycle message must be
refusable without signing in, because the alternative control a reader has is the spam button.
And no message may carry rubric content, because email is forwarded, archived and indexed by
systems this application does not control.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from httpx import AsyncClient

from core.config.settings import settings
from core.constants.enums import GradingStatus, SessionStatus, SessionType
from core.cruds.session_crud import CRUDSession
from core.cruds.skill_score_crud import CRUDSkillScore
from core.cruds.user_crud import CRUDProfile, CRUDUser
from core.services.email import templates
from core.services.email.email_service import EmailService
from core.services.email.provider import EmailProvider
from core.services.email.types import EmailKind, EmailMessage, SendResult
from core.services.email.unsubscribe import mint_token, verify_token
from tests.conftest import requires_database
from tests.factories import (
    make_attempt,
    make_gradeable_question,
    make_session,
    make_user,
    utc_now,
)

PASSWORD = "correct-horse-battery-staple"


class RecordingEmailProvider(EmailProvider):
    """Captures messages instead of sending them."""

    name = "recording"

    def __init__(self, *, deliver: bool = True) -> None:
        """
        Initialise the recorder.

        Args:
            deliver: Whether to report each send as accepted.
        """
        self.sent: list[EmailMessage] = []
        self.deliver = deliver

    async def send(self, message: EmailMessage) -> SendResult:
        """Record the message and report the configured outcome. See ``EmailProvider``."""
        self.sent.append(message)
        if not self.deliver:
            return SendResult(delivered=False, error="provider unavailable")
        return SendResult(delivered=True, provider_message_id="rec_1")


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


async def graded_diagnostic(user_id: uuid.UUID, *, grading_status: str = GradingStatus.GRADED):
    """
    Build a completed diagnostic with one attempt in the given grading state.

    Args:
        user_id: Owning user.
        grading_status: State of the single attempt.

    Returns:
        Session: The completed diagnostic.
    """
    question, version = await make_gradeable_question()
    session_row = await make_session(
        user_id=user_id,
        type=SessionType.DIAGNOSTIC,
        status=SessionStatus.COMPLETED,
        finished_at=utc_now(),
        questions=[{"position": 0, "question_id": question.id, "question_version_id": version.id}],
    )
    graded_fields: dict[str, Any] = {"grading_status": grading_status}
    if grading_status == GradingStatus.GRADED:
        graded_fields |= {"score": 62, "band": "developing", "graded_at": utc_now()}
    await make_attempt(
        user_id=user_id,
        session_id=session_row.id,
        question_id=question.id,
        question_version_id=version.id,
        **graded_fields,
    )
    return session_row


# ------------------------------------------------------------------------------------------
# Rendering
# ------------------------------------------------------------------------------------------


class TestTemplates:
    """What actually goes in the message."""

    def test_the_results_email_carries_no_rubric_content(self) -> None:
        """Email is forwarded, archived and indexed elsewhere; a leaked rubric leaks forever."""
        rendered = templates.render_diagnostic_results(
            overall=62,
            weakest_name="Valuation",
            weakest_score=48,
            strongest_name="Accounting",
            measured_categories=8,
            session_id=str(uuid.uuid4()),
        )

        body = f"{rendered.html} {rendered.text}".lower()
        for forbidden in ("ideal answer", "expected concept", "common mistake", "rubric"):
            assert forbidden not in body

    def test_the_results_email_leads_with_the_number(self) -> None:
        """The subject has to survive a notification preview, which is a dozen characters."""
        rendered = templates.render_diagnostic_results(
            overall=62,
            weakest_name="Valuation",
            weakest_score=48,
            strongest_name=None,
            measured_categories=8,
            session_id="abc",
        )

        assert "62" in rendered.subject
        assert "Valuation is your weakest area at 48." in rendered.text

    def test_an_ungradeable_diagnostic_says_so_rather_than_inventing_a_score(self) -> None:
        """A number computed from partial evidence is wrong, not early."""
        rendered = templates.render_diagnostic_results(
            overall=None,
            weakest_name=None,
            weakest_score=None,
            strongest_name=None,
            measured_categories=0,
            session_id="abc",
        )

        assert "could not" in rendered.subject.lower()
        assert "/100" not in rendered.text

    def test_interpolated_values_are_escaped(self) -> None:
        """Category names reach the HTML from data, so they are escaped at the point of use."""
        rendered = templates.render_diagnostic_results(
            overall=50,
            weakest_name="<script>alert('x')</script>",
            weakest_score=10,
            strongest_name=None,
            measured_categories=1,
            session_id="abc",
        )

        assert "<script>" not in rendered.html
        assert "&lt;script&gt;" in rendered.html

    def test_every_message_has_a_text_alternative(self) -> None:
        """HTML-only mail scores as more likely to be spam, and universities filter hard."""
        messages = [
            templates.render_diagnostic_results(
                overall=70,
                weakest_name="DCF",
                weakest_score=55,
                strongest_name="LBO",
                measured_categories=8,
                session_id="abc",
            ),
            templates.render_payment_receipt(
                plan_name="Season Pass", access_until="1 January 2027"
            ),
            templates.render_weak_area_nudge(
                weakest_name="DCF",
                weakest_score=55,
                review_due_count=2,
                unsubscribe="https://example.test/unsubscribe?token=t",
            ),
        ]

        for message in messages:
            assert message.text.strip()
            assert message.html.strip()
            assert message.subject.strip()

    def test_the_nudge_carries_a_visible_unsubscribe(self) -> None:
        """A lifecycle message a reader cannot stop is one they will report instead."""
        link = "https://example.test/unsubscribe?token=abc"
        rendered = templates.render_weak_area_nudge(
            weakest_name="DCF", weakest_score=55, review_due_count=2, unsubscribe=link
        )

        assert link in rendered.html
        assert "Turn these off" in rendered.html

    def test_transactional_mail_offers_no_unsubscribe(self) -> None:
        """There is nothing to unsubscribe from: results are a consequence, not a list."""
        rendered = templates.render_payment_receipt(plan_name="Pro", access_until=None)

        assert "unsubscribe" not in rendered.html.lower()

    def test_the_receipt_does_not_invent_an_amount(self) -> None:
        """The payment provider issues the tax receipt; a wrong amount here is worse than none."""
        rendered = templates.render_payment_receipt(plan_name="Pro", access_until=None)

        assert "$" not in rendered.text
        assert "£" not in rendered.text


class TestUnsubscribeTokens:
    """The thing standing between a public endpoint and someone else's preferences."""

    def test_a_token_round_trips(self) -> None:
        """The recipient is recoverable from their own token."""
        user_id = uuid.uuid4()

        assert verify_token(mint_token(user_id=user_id)) == user_id

    def test_a_tampered_token_is_rejected(self) -> None:
        """Editing the signature invalidates it."""
        token = mint_token(user_id=uuid.uuid4())
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")

        assert verify_token(tampered) is None

    def test_a_substituted_user_is_rejected(self) -> None:
        """The signature covers the user ID, so the recipient cannot be swapped."""
        token = mint_token(user_id=uuid.uuid4())
        _, _, signature = token.partition(".")

        assert verify_token(f"{uuid.uuid4()}.{signature}") is None

    def test_a_token_is_scoped_to_its_purpose(self) -> None:
        """A study-reminder token must not be replayable against another preference."""
        token = mint_token(user_id=uuid.uuid4())

        assert verify_token(token, purpose="something_else") is None

    def test_malformed_input_is_rejected_without_raising(self) -> None:
        """The endpoint is public, so it is fed junk as a matter of course."""
        for junk in ("", "nonsense", "not-a-uuid.sig", ".", "a.b.c"):
            assert verify_token(junk) is None


# ------------------------------------------------------------------------------------------
# Sending
# ------------------------------------------------------------------------------------------


@requires_database
class TestDiagnosticResultsEmail:
    """Exactly once, and only when there is a real result to report."""

    async def test_a_graded_diagnostic_is_mailed_and_marked(self, migrated_database: None) -> None:
        """The send marker is what makes the sweep idempotent."""
        user = await make_user()
        session_row = await graded_diagnostic(user.id)
        await CRUDSkillScore().upsert(
            user_id=user.id,
            category_slug="valuation",
            score=62,
            evidence_count=1,
            last_attempt_at=utc_now(),
        )
        provider = RecordingEmailProvider()

        summary = await EmailService(provider=provider).deliver_pending_diagnostic_results()

        assert summary == {"examined": 1, "sent": 1, "skipped": 0, "failed": 0}
        assert provider.sent[0].to == user.email
        assert provider.sent[0].kind == EmailKind.DIAGNOSTIC_RESULTS
        refreshed = await CRUDSession().get_by_id(session_id=session_row.id)
        assert refreshed is not None
        assert refreshed.results_email_sent_at is not None

    async def test_the_sweep_does_not_send_twice(self, migrated_database: None) -> None:
        """A second pass finds nothing, because the marker was written."""
        user = await make_user()
        await graded_diagnostic(user.id)
        service = EmailService(provider=RecordingEmailProvider())
        await service.deliver_pending_diagnostic_results()

        provider = RecordingEmailProvider()
        summary = await EmailService(provider=provider).deliver_pending_diagnostic_results()

        assert summary["examined"] == 0
        assert provider.sent == []

    async def test_a_failed_send_is_retried_rather_than_lost(self, migrated_database: None) -> None:
        """The marker is written after the provider accepts, never before."""
        user = await make_user()
        session_row = await graded_diagnostic(user.id)

        failing = RecordingEmailProvider(deliver=False)
        first = await EmailService(provider=failing).deliver_pending_diagnostic_results()
        assert first["failed"] == 1
        refreshed = await CRUDSession().get_by_id(session_id=session_row.id)
        assert refreshed is not None
        assert refreshed.results_email_sent_at is None

        working = RecordingEmailProvider()
        second = await EmailService(provider=working).deliver_pending_diagnostic_results()

        assert second["sent"] == 1
        assert len(working.sent) == 1

    async def test_a_diagnostic_still_grading_is_not_mailed(self, migrated_database: None) -> None:
        """Mailing a score computed from half the answers is a wrong number, not an early one."""
        user = await make_user()
        await graded_diagnostic(user.id, grading_status=GradingStatus.PENDING)
        provider = RecordingEmailProvider()

        summary = await EmailService(provider=provider).deliver_pending_diagnostic_results()

        assert summary["examined"] == 0
        assert provider.sent == []

    async def test_a_wholly_failed_diagnostic_is_still_mailed(
        self, migrated_database: None
    ) -> None:
        """Grading failed, so there is nothing left to wait for — and saying so is the honest act."""
        user = await make_user()
        await graded_diagnostic(user.id, grading_status=GradingStatus.FAILED)
        provider = RecordingEmailProvider()

        summary = await EmailService(provider=provider).deliver_pending_diagnostic_results()

        assert summary["sent"] == 1
        assert "could not" in provider.sent[0].subject.lower()

    async def test_an_unfinished_diagnostic_is_never_mailed(self, migrated_database: None) -> None:
        """A student still sitting the assessment has no results to receive."""
        user = await make_user()
        await make_session(user_id=user.id, type=SessionType.DIAGNOSTIC)
        provider = RecordingEmailProvider()

        summary = await EmailService(provider=provider).deliver_pending_diagnostic_results()

        assert summary["examined"] == 0

    async def test_a_practice_session_is_not_mailed(self, migrated_database: None) -> None:
        """This email is about the diagnostic; practice has its own summary in the product."""
        user = await make_user()
        await make_session(
            user_id=user.id,
            type=SessionType.PRACTICE,
            status=SessionStatus.COMPLETED,
            finished_at=utc_now(),
        )
        provider = RecordingEmailProvider()

        summary = await EmailService(provider=provider).deliver_pending_diagnostic_results()

        assert summary["examined"] == 0


@requires_database
class TestWeakAreaNudge:
    """The one lifecycle email, and every reason not to send it."""

    async def _student_with_mastery(self, *, score: int = 44) -> Any:
        """
        Build a student with enough graded evidence to be worth nudging.

        Args:
            score: Mastery score for their weakest category.

        Returns:
            User: The created student.
        """
        user = await make_user()
        await CRUDProfile().create(user_id=user.id)
        await CRUDSkillScore().upsert(
            user_id=user.id,
            category_slug="valuation",
            score=score,
            evidence_count=5,
            last_attempt_at=utc_now(),
        )
        return user

    async def test_a_student_with_a_weak_area_is_nudged(self, migrated_database: None) -> None:
        """The message names the category and its score."""
        await self._student_with_mastery()
        provider = RecordingEmailProvider()

        summary = await EmailService(provider=provider).send_weekly_nudges()

        assert summary["sent"] == 1
        assert provider.sent[0].kind == EmailKind.WEAK_AREA_NUDGE
        assert "44" in provider.sent[0].text

    async def test_the_nudge_carries_an_unsubscribe_url(self, migrated_database: None) -> None:
        """Set on the message so the provider can add the one-click headers."""
        await self._student_with_mastery()
        provider = RecordingEmailProvider()

        await EmailService(provider=provider).send_weekly_nudges()

        assert provider.sent[0].unsubscribe_url is not None
        assert "/unsubscribe?token=" in provider.sent[0].unsubscribe_url

    async def test_a_student_with_no_evidence_is_not_nudged(self, migrated_database: None) -> None:
        """'Practise your weakest area' to somebody with no measured areas is spam."""
        user = await make_user()
        await CRUDProfile().create(user_id=user.id)
        provider = RecordingEmailProvider()

        summary = await EmailService(provider=provider).send_weekly_nudges()

        assert summary["examined"] == 1
        assert summary["skipped"] == 1
        assert provider.sent == []

    async def test_a_skipped_student_keeps_their_eligibility(self, migrated_database: None) -> None:
        """Marking a skip would push them a week further back every week, forever."""
        user = await make_user()
        await CRUDProfile().create(user_id=user.id)
        await EmailService(provider=RecordingEmailProvider()).send_weekly_nudges()

        profile = await CRUDProfile().get_by_user_id(user_id=user.id)

        assert profile is not None
        assert profile.last_nudge_email_at is None

    async def test_an_unsubscribed_student_is_never_selected(self, migrated_database: None) -> None:
        """Excluded by the query, not filtered afterwards."""
        user = await self._student_with_mastery()
        await CRUDProfile().update(user_id=user.id, obj_in={"study_reminder_emails": False})
        provider = RecordingEmailProvider()

        summary = await EmailService(provider=provider).send_weekly_nudges()

        assert summary["examined"] == 0
        assert provider.sent == []

    async def test_a_recently_nudged_student_is_not_nudged_again(
        self, migrated_database: None
    ) -> None:
        """The interval is per recipient, so a re-run cannot double-send."""
        await self._student_with_mastery()
        await EmailService(provider=RecordingEmailProvider()).send_weekly_nudges()

        provider = RecordingEmailProvider()
        summary = await EmailService(provider=provider).send_weekly_nudges()

        assert summary["examined"] == 0
        assert provider.sent == []

    async def test_eligibility_returns_once_the_interval_has_passed(
        self, migrated_database: None
    ) -> None:
        """A weekly email is weekly, not once."""
        user = await self._student_with_mastery()
        await CRUDProfile().update(
            user_id=user.id,
            obj_in={
                "last_nudge_email_at": datetime.now(UTC)
                - timedelta(days=settings.NUDGE_MIN_INTERVAL_DAYS + 1)
            },
        )
        provider = RecordingEmailProvider()

        summary = await EmailService(provider=provider).send_weekly_nudges()

        assert summary["sent"] == 1

    async def test_a_failed_nudge_leaves_the_student_eligible(
        self, migrated_database: None
    ) -> None:
        """A provider outage must not silently skip somebody's week."""
        user = await self._student_with_mastery()

        await EmailService(provider=RecordingEmailProvider(deliver=False)).send_weekly_nudges()

        profile = await CRUDProfile().get_by_user_id(user_id=user.id)
        assert profile is not None
        assert profile.last_nudge_email_at is None


# ------------------------------------------------------------------------------------------
# Preferences over HTTP
# ------------------------------------------------------------------------------------------


@requires_database
class TestEmailPreferences:
    """What a student can change, signed in and signed out."""

    async def test_preferences_require_authentication(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """Preferences are personal; there is no anonymous read."""
        assert (await client.get("/v1/account/email-preferences")).status_code == 401

    async def test_study_reminders_are_on_by_default(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """A reminder is the product working, unlike marketing, which is opt-in."""
        await signed_in_user(client)

        body = (await client.get("/v1/account/email-preferences")).json()

        assert body["study_reminder_emails"] is True
        assert body["marketing_emails_opt_in"] is False

    async def test_a_student_can_turn_reminders_off_and_on(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """Signed in, the preference moves both ways."""
        await signed_in_user(client)

        off = await client.put(
            "/v1/account/email-preferences",
            json={"study_reminder_emails": False, "marketing_emails_opt_in": False},
        )
        assert off.json()["study_reminder_emails"] is False

        on = await client.put(
            "/v1/account/email-preferences",
            json={"study_reminder_emails": True, "marketing_emails_opt_in": False},
        )
        assert on.json()["study_reminder_emails"] is True

    async def test_unsubscribe_works_without_a_session(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """The whole point: stopping mail must not require remembering a password."""
        user = await make_user()
        await CRUDProfile().create(user_id=user.id)

        response = await client.post(
            "/v1/emails/unsubscribe", json={"token": mint_token(user_id=user.id)}
        )

        assert response.status_code == 200
        profile = await CRUDProfile().get_by_user_id(user_id=user.id)
        assert profile is not None
        assert profile.study_reminder_emails is False

    async def test_an_unsubscribe_link_cannot_resubscribe(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """The endpoint writes False; it does not take a value from the caller."""
        user = await make_user()
        await CRUDProfile().create(user_id=user.id)
        token = mint_token(user_id=user.id)
        await client.post("/v1/emails/unsubscribe", json={"token": token})

        await client.post(
            "/v1/emails/unsubscribe", json={"token": token, "study_reminder_emails": True}
        )

        profile = await CRUDProfile().get_by_user_id(user_id=user.id)
        assert profile is not None
        assert profile.study_reminder_emails is False

    async def test_an_invalid_token_is_answered_identically(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """Distinguishing them would make this a way to test whether an address is registered."""
        user = await make_user()
        await CRUDProfile().create(user_id=user.id)
        valid = await client.post(
            "/v1/emails/unsubscribe", json={"token": mint_token(user_id=user.id)}
        )
        invalid = await client.post(
            "/v1/emails/unsubscribe", json={"token": f"{uuid.uuid4()}.notasignature"}
        )

        assert valid.status_code == invalid.status_code == 200
        assert valid.json() == invalid.json()

    async def test_unsubscribing_stops_the_nudge(
        self, client: AsyncClient, migrated_database: None
    ) -> None:
        """End to end: the link a student clicks actually stops the mail."""
        user = await make_user()
        await CRUDProfile().create(user_id=user.id)
        await CRUDSkillScore().upsert(
            user_id=user.id,
            category_slug="valuation",
            score=40,
            evidence_count=5,
            last_attempt_at=utc_now(),
        )
        await client.post("/v1/emails/unsubscribe", json={"token": mint_token(user_id=user.id)})

        provider = RecordingEmailProvider()
        summary = await EmailService(provider=provider).send_weekly_nudges()

        assert summary["examined"] == 0
        assert provider.sent == []
