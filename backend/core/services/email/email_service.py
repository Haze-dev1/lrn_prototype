"""Sending the product's three emails.

Each send follows the same shape, and the order matters: decide whether this student should
receive it, render it, hand it to the provider, and only then record that it went. Recording
first would turn one provider outage into a results email that is never sent and never retried —
so the marker is written after the provider accepts, and a failure simply leaves the work for the
next sweep.

Nothing here raises for an ordinary delivery failure. Email is a side effect of the product
working, never a precondition for it: a student whose results email bounced must still see their
results, and a webhook must not return a 5xx — causing Stripe to retry a payment event — because
a mail server was slow.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core import logger
from core.config.settings import settings
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.category_crud import CRUDCategory
from core.cruds.session_crud import CRUDSession
from core.cruds.skill_score_crud import CRUDSkillScore
from core.cruds.user_crud import CRUDProfile, CRUDUser
from core.models.session_model import Session
from core.services.email import templates
from core.services.email.provider import EmailProvider, get_email_provider
from core.services.email.types import EmailKind, EmailMessage
from core.services.email.unsubscribe import unsubscribe_url
from core.services.sessions.practice_service import QuestionHistory

logging = logger(__name__)


@dataclass(frozen=True)
class SweepSummary:
    """What one email sweep did, for the job log."""

    examined: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0

    def as_dict(self) -> dict[str, int]:
        """
        Render the summary for logging.

        Returns:
            dict[str, int]: Counts by outcome.
        """
        return {
            "examined": self.examined,
            "sent": self.sent,
            "skipped": self.skipped,
            "failed": self.failed,
        }


class EmailService:
    """Renders and delivers the product's transactional and lifecycle email."""

    def __init__(self, provider: EmailProvider | None = None) -> None:
        """
        Initialise the service with a provider and the CRUD layers it reads from.

        Args:
            provider: Email provider to use; defaults to the configured one.
        """
        self.provider = provider or get_email_provider()
        self.CRUDUser = CRUDUser()
        self.CRUDProfile = CRUDProfile()
        self.CRUDSession = CRUDSession()
        self.CRUDSkillScore = CRUDSkillScore()
        self.CRUDAttempt = CRUDAttempt()
        self.CRUDCategory = CRUDCategory()

    async def _deliver(self, message: EmailMessage) -> bool:
        """
        Hand one message to the provider and report whether it was accepted.

        Args:
            message: The rendered message.

        Returns:
            bool: True when the provider accepted it.
        """
        result = await self.provider.send(message)
        if not result.delivered:
            logging.error(f"Failed to send a {message.kind} email: {result.error}")
        return result.delivered

    # -- Diagnostic results ---------------------------------------------------------------

    async def send_diagnostic_results(self, *, session_row: Session) -> bool:
        """
        Mail one student the shape of their diagnostic result.

        Transactional: it is a consequence of finishing the diagnostic, so no preference gates it.
        A student who sat a 24-question assessment is owed the outcome.

        The numbers come from stored mastery, the same source the results page reads, so the email
        and the page can never disagree about how ready a student is.

        Args:
            session_row: The completed, fully graded diagnostic.

        Returns:
            bool: True when the message was accepted by the provider.

        Raises:
            Exception: If reading the student or their mastery fails.
        """
        logging.info("Executing EmailService.send_diagnostic_results")
        user = await self.CRUDUser.get_by_id(user_id=session_row.user_id)
        if user is None:
            # The account was deleted between finishing the diagnostic and this sweep running.
            logging.warning(f"No user for diagnostic {session_row.id}; nothing to send")
            return False

        scores = await self.CRUDSkillScore.list_for_user(user_id=user.id)
        measured = [score for score in scores if score.evidence_count > 0]
        names = {category.slug: category.name for category in await self.CRUDCategory.list_all()}

        overall = (
            round(sum(score.score for score in measured) / len(measured)) if measured else None
        )
        # `list_for_user` orders weakest first, which is the order every surface reads them in.
        weakest = measured[0] if measured else None
        strongest = measured[-1] if measured else None

        rendered = templates.render_diagnostic_results(
            overall=overall,
            weakest_name=names.get(weakest.category_slug, weakest.category_slug)
            if weakest
            else None,
            weakest_score=weakest.score if weakest else None,
            strongest_name=names.get(strongest.category_slug, strongest.category_slug)
            if strongest and strongest is not weakest
            else None,
            measured_categories=len(measured),
            session_id=str(session_row.id),
        )

        return await self._deliver(
            EmailMessage(
                to=user.email,
                subject=rendered.subject,
                html=rendered.html,
                text=rendered.text,
                kind=EmailKind.DIAGNOSTIC_RESULTS,
            )
        )

    async def deliver_pending_diagnostic_results(self) -> dict[str, int]:
        """
        Send the results email for every diagnostic that is finished, graded and unmailed.

        A sweep rather than a send at completion time, because grading is asynchronous: the moment
        a student finishes their last answer, none of it may be graded yet. Driving the email from
        stored state instead of from an event also means a crash, a deploy, or a provider outage
        between the two costs a delay rather than the email.

        Returns:
            dict[str, int]: Counts by outcome, for the job log.

        Raises:
            Exception: If the underlying reads fail.
        """
        logging.info("Executing EmailService.deliver_pending_diagnostic_results")
        pending = await self.CRUDSession.list_diagnostics_awaiting_results_email()
        examined = sent = failed = 0

        for session_row in pending:
            examined += 1
            try:
                delivered = await self.send_diagnostic_results(session_row=session_row)
            except Exception as error:
                # One unsendable message must not abandon the sweep; the rest are other students.
                logging.error(f"Error sending results for diagnostic {session_row.id}: {error}")
                delivered = False

            if delivered:
                await self.CRUDSession.mark_results_email_sent(session_id=session_row.id)
                sent += 1
            else:
                failed += 1

        summary = SweepSummary(examined=examined, sent=sent, failed=failed).as_dict()
        if examined:
            logging.info(f"deliver_pending_diagnostic_results {summary}")
        return summary

    # -- Payment receipt ------------------------------------------------------------------

    async def send_payment_receipt(
        self, *, user_id: uuid.UUID, plan_name: str, access_until: datetime | None
    ) -> bool:
        """
        Confirm to a student that paid access has started.

        Transactional, and best-effort by design: it is sent from the webhook path, and a mail
        failure there must never become a non-2xx response. Stripe retries a non-2xx, and paying
        for the retry of a payment event because an SMTP server was slow is the wrong trade.

        Args:
            user_id: The paying student.
            plan_name: Human name of the plan they bought.
            access_until: When access ends, or None for a renewing subscription.

        Returns:
            bool: True when the message was accepted by the provider.
        """
        try:
            logging.info("Executing EmailService.send_payment_receipt")
            user = await self.CRUDUser.get_by_id(user_id=user_id)
            if user is None:
                logging.warning("No user for a payment receipt; nothing to send")
                return False

            rendered = templates.render_payment_receipt(
                plan_name=plan_name,
                access_until=access_until.strftime("%-d %B %Y") if access_until else None,
            )
            return await self._deliver(
                EmailMessage(
                    to=user.email,
                    subject=rendered.subject,
                    html=rendered.html,
                    text=rendered.text,
                    kind=EmailKind.PAYMENT_RECEIPT,
                )
            )
        except Exception as error:
            logging.error(f"Error in EmailService.send_payment_receipt: {error}")
            return False

    # -- Weak-area nudge ------------------------------------------------------------------

    async def send_weak_area_nudge(self, *, user_id: uuid.UUID, email: str) -> bool:
        """
        Mail one student the single area worth working on this week.

        Skipped, not sent empty, when the student has no measured weakness. A weekly email that
        says "practise your weakest area" to somebody with no measured areas is spam with the
        product's name on it, and the fastest way to lose the address entirely.

        Args:
            user_id: The recipient.
            email: Their address.

        Returns:
            bool: True when a message was sent; False when there was nothing worth sending.

        Raises:
            Exception: If reading mastery or history fails.
        """
        logging.info("Executing EmailService.send_weak_area_nudge")
        scores = await self.CRUDSkillScore.list_for_user(user_id=user_id)
        measured = [score for score in scores if score.evidence_count > 0]
        if not measured:
            return False

        total_evidence = sum(score.evidence_count for score in measured)
        if total_evidence < settings.NUDGE_MIN_GRADED_ATTEMPTS:
            return False

        weakest = measured[0]
        names = {category.slug: category.name for category in await self.CRUDCategory.list_all()}

        now = datetime.now(UTC)
        review_due = 0
        for (
            _,
            attempt_count,
            latest_score,
            graded_at,
        ) in await self.CRUDAttempt.list_question_history(user_id=user_id):
            history = QuestionHistory(
                attempt_count=attempt_count, latest_score=latest_score, latest_graded_at=graded_at
            )
            if history.is_due_for_review(now=now):
                review_due += 1

        rendered = templates.render_weak_area_nudge(
            weakest_name=names.get(weakest.category_slug, weakest.category_slug),
            weakest_score=weakest.score,
            review_due_count=review_due,
            unsubscribe=unsubscribe_url(user_id=user_id),
        )

        return await self._deliver(
            EmailMessage(
                to=email,
                subject=rendered.subject,
                html=rendered.html,
                text=rendered.text,
                kind=EmailKind.WEAK_AREA_NUDGE,
                unsubscribe_url=unsubscribe_url(user_id=user_id),
            )
        )

    async def send_weekly_nudges(self) -> dict[str, int]:
        """
        Send the weak-area nudge to every eligible student.

        Two filters, in this order and for different reasons. The database answers "may we mail
        this person" — active account, reminders on, not mailed inside the interval — because
        that is a query. Whether there is anything worth saying is decided per student here,
        because it needs their mastery.

        A student who is skipped for having nothing to say keeps their eligibility: the marker is
        only set when a message actually goes out, so next week they are considered again rather
        than silently pushed a week further back each time.

        Returns:
            dict[str, int]: Counts by outcome, for the job log.

        Raises:
            Exception: If the underlying reads fail.
        """
        logging.info("Executing EmailService.send_weekly_nudges")
        cutoff = datetime.now(UTC) - timedelta(days=settings.NUDGE_MIN_INTERVAL_DAYS)
        candidates = await self.CRUDProfile.list_nudge_candidates(not_since=cutoff)
        examined = sent = skipped = failed = 0

        for user, _profile in candidates:
            examined += 1
            try:
                delivered = await self.send_weak_area_nudge(user_id=user.id, email=user.email)
            except Exception as error:
                logging.error(f"Error sending a nudge to user {user.id}: {error}")
                failed += 1
                continue

            if delivered:
                await self.CRUDProfile.mark_nudge_sent(user_id=user.id)
                sent += 1
            else:
                # Nothing worth saying this week. Deliberately not marked, so this student is
                # considered again next week rather than pushed back another interval.
                skipped += 1

        summary = SweepSummary(
            examined=examined, sent=sent, skipped=skipped, failed=failed
        ).as_dict()
        if examined:
            logging.info(f"send_weekly_nudges {summary}")
        return summary
