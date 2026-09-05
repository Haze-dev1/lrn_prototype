"""Server-authoritative access decisions.

Every gated operation asks this module the same question and takes its answer. The interface may
hide a control it knows is unavailable, but hiding is presentation: an API request that arrives
anyway is refused here, so a modified client, a stale tab, or a direct curl gets exactly the same
answer as the button.

Free access is the absence of an active entitlement, never a stored "free" value. That makes the
check one query with one meaning — does an unexpired grant exist — rather than a comparison that
a new plan name could quietly fall outside of.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from core import logger
from core.config.settings import settings
from core.constants.enums import Plan, SessionType
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.billing_crud import CRUDEntitlement, CRUDSubscription
from core.cruds.session_crud import CRUDSession
from core.models.user_model import User
from core.services.analytics.events import AnalyticsEvent
from core.services.analytics.service import track
from core.services.billing.plans import FREE_PLAN, plan_for_entitlement

logging = logger(__name__)

# The free diagnostic allowance. Not configurable: "one free measurement" is the shape of the
# product's offer, not a tuning parameter, and a deployment that changed it would be selling
# something different.
FREE_DIAGNOSTICS = 1

# The grading allowance resets on a rolling window rather than at midnight. A calendar reset
# hands two allowances to anyone willing to wait for it, and gives students in different
# timezones different products.
GRADING_WINDOW_HOURS = 24


class EntitlementRequired(Exception):
    """A free-tier caller reached a limit or a paid-only capability.

    Carries the numbers behind the refusal rather than a bare message, so the interface can say
    "you have used 3 of 3 practice sets" instead of "upgrade required" — a student is owed the
    reason, and a message that only sells is a worse product than one that explains.
    """

    def __init__(
        self, *, reason: str, message: str, used: int | None = None, limit: int | None = None
    ) -> None:
        """
        Build a refusal carrying its own explanation.

        Args:
            reason: Stable machine-readable code for the interface to branch on.
            message: Sentence shown to the student.
            used: How much of the allowance has been consumed, when there is one.
            limit: The allowance, when there is one.
        """
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.used = used
        self.limit = limit

    def as_detail(self) -> dict[str, object]:
        """
        Render the refusal as the structured detail an API response carries.

        A shape rather than a sentence, because the interface needs to branch on the reason to
        choose the right upgrade prompt, and needs the numbers to show a meter. Deliberately a
        plain dict and not an HTTP concern: this class knows what was refused, not how the refusal
        is transported.

        Returns:
            dict[str, object]: Reason code, message, and the allowance behind it.
        """
        return {
            "reason": self.reason,
            "message": self.message,
            "used": self.used,
            "limit": self.limit,
            "upgrade_url": "/pricing",
        }


@dataclass(frozen=True)
class FreeTierUsage:
    """What a free account has used of each allowance, and what remains."""

    diagnostics_taken: int
    practice_sessions_used: int
    practice_sessions_limit: int
    graded_today: int
    daily_grade_limit: int

    @property
    def practice_sessions_remaining(self) -> int:
        """
        Return practice sets still available today under the free allowance.

        Returns:
            int: Remaining sets, never negative.
        """
        return max(0, self.practice_sessions_limit - self.practice_sessions_used)

    @property
    def grades_remaining_today(self) -> int:
        """
        Return graded answers still available in the current 24-hour window.

        Returns:
            int: Remaining graded answers, never negative.
        """
        return max(0, self.daily_grade_limit - self.graded_today)


@dataclass(frozen=True)
class AccessState:
    """Everything the application knows about one user's access right now.

    Assembled once per request that needs it and passed around, rather than each caller
    re-deriving it — a dashboard that computes access differently from the endpoint that enforces
    it is how a paywall ends up showing to someone who paid.
    """

    plan: Plan
    entitlement: str | None
    active_until: datetime | None
    #: When access most recently ended, for a lapsed Season Pass or a cancelled subscription.
    expired_at: datetime | None
    cancel_at_period_end: bool
    has_billing_account: bool
    usage: FreeTierUsage

    @property
    def is_paid(self) -> bool:
        """
        Report whether the user currently holds paid access.

        Returns:
            bool: True when an active, unexpired entitlement exists.
        """
        return self.entitlement is not None

    @property
    def previously_paid(self) -> bool:
        """
        Report whether the user has held paid access that has since ended.

        Drives the "your access expired on <date>" message, which is a different thing to say
        from "here is what Pro costs".

        Returns:
            bool: True when access has lapsed and has not been replaced.
        """
        return not self.is_paid and self.expired_at is not None

    @property
    def can_start_practice(self) -> bool:
        """
        Report whether another practice set may be started.

        Returns:
            bool: True for paid users, or a free user with allowance left.
        """
        return self.is_paid or self.usage.practice_sessions_remaining > 0

    @property
    def can_grade_answer(self) -> bool:
        """
        Report whether another practice answer may be graded today.

        The diagnostic is exempt and is not asked about here: it is the free tier's whole point,
        and a 24-question sitting would exhaust any sane daily cap on its own.

        Returns:
            bool: True for paid users, or a free user within today's grading cap.
        """
        return self.is_paid or self.usage.grades_remaining_today > 0

    @property
    def can_start_new_diagnostic(self) -> bool:
        """
        Report whether a *new* diagnostic may be composed.

        Resuming or re-reading an existing one is always allowed; this governs sitting a second
        one, which is a paid capability. A free account gets one measurement, which is what makes
        the results page mean something.

        Returns:
            bool: True for paid users, or a free user who has never sat one.
        """
        return self.is_paid or self.usage.diagnostics_taken < FREE_DIAGNOSTICS


class EntitlementService:
    """Resolves and enforces what a user is allowed to do."""

    def __init__(self) -> None:
        """Initialise the service with the CRUD layers it reads from."""
        self.CRUDEntitlement = CRUDEntitlement()
        self.CRUDSubscription = CRUDSubscription()
        self.CRUDSession = CRUDSession()
        self.CRUDAttempt = CRUDAttempt()

    async def access_for(self, *, user: User) -> AccessState:
        """
        Assemble the caller's current access and free-tier usage.

        Usage counters are read for paid users too, even though no limit applies to them. The cost
        is two indexed counts, and the alternative is a branch whose untested half is the one that
        runs the moment a subscription lapses mid-session.

        Args:
            user: The user to describe.

        Returns:
            AccessState: Plan, entitlement window, and free-tier usage.

        Raises:
            Exception: If the underlying reads fail.
        """
        try:
            logging.info("Executing EntitlementService.access_for")
            active = await self.CRUDEntitlement.get_active_for_user(user_id=user.id)
            latest = active or await self.CRUDEntitlement.get_latest_for_user(user_id=user.id)

            plan = FREE_PLAN.plan
            if active is not None:
                definition = plan_for_entitlement(active.entitlement)
                plan = definition.plan if definition else FREE_PLAN.plan

            expired_at: datetime | None = None
            if active is None and latest is not None:
                # Both endings are the same thing to a student: access they had, and no longer
                # have. A revoked grant has no end date of its own, so the moment it was revoked
                # is the honest answer.
                expired_at = latest.active_until or latest.updated_at

            cancel_at_period_end = False
            customer_id = await self.CRUDSubscription.get_customer_id_for_user(user_id=user.id)
            if active is not None and active.source_subscription_id is not None:
                for subscription in await self.CRUDSubscription.list_for_user(user_id=user.id):
                    if subscription.id == active.source_subscription_id:
                        cancel_at_period_end = subscription.cancel_at_period_end
                        break

            usage = await self.usage_for(user=user)
            return AccessState(
                plan=plan,
                entitlement=active.entitlement if active else None,
                active_until=active.active_until if active else None,
                expired_at=expired_at,
                cancel_at_period_end=cancel_at_period_end,
                has_billing_account=customer_id is not None,
                usage=usage,
            )
        except Exception as error:
            logging.error(f"Error in EntitlementService.access_for: {error}")
            raise error

    async def usage_for(self, *, user: User) -> FreeTierUsage:
        """
        Count what the user has consumed of each free allowance.

        The grading window is a rolling 24 hours rather than a calendar day. A calendar reset
        would give a student in one timezone a full allowance at 01:00 local and one in another
        an empty one, and would let anyone with patience take two allowances back to back across
        midnight.

        Args:
            user: The user to count for.

        Returns:
            FreeTierUsage: Consumption and limits.

        Raises:
            Exception: If the underlying reads fail.
        """
        try:
            logging.info("Executing EntitlementService.usage_for")
            diagnostics = await self.CRUDSession.count_by_type(
                user_id=user.id, session_type=SessionType.DIAGNOSTIC
            )
            # Counted by sets actually answered, not by sets created. Starting a set abandons
            # the previous one, so a raw session count would charge a student for reconsidering
            # the set size — and excluding abandoned sets would never charge them at all, since
            # only one non-abandoned practice session ever exists.
            practice = await self.CRUDSession.count_practice_sets_answered(user_id=user.id)
            window_start = datetime.now(UTC) - timedelta(hours=GRADING_WINDOW_HOURS)
            graded = await self.CRUDAttempt.count_graded_since(user_id=user.id, since=window_start)
            return FreeTierUsage(
                diagnostics_taken=diagnostics,
                practice_sessions_used=practice,
                practice_sessions_limit=settings.FREE_PRACTICE_SESSIONS,
                graded_today=graded,
                daily_grade_limit=settings.FREE_DAILY_GRADED_ATTEMPTS,
            )
        except Exception as error:
            logging.error(f"Error in EntitlementService.usage_for: {error}")
            raise error

    async def has_paid_access(self, *, user: User) -> bool:
        """
        Report whether the user currently holds an active paid grant.

        The narrow question the gates below start with. ``access_for`` answers it too, but it
        also assembles counters and subscription state that a gate does not need — and the
        grading gate runs on every answer a student submits.

        Args:
            user: The user to check.

        Returns:
            bool: True when an active, unexpired grant exists.

        Raises:
            Exception: If the database read fails.
        """
        return await self.CRUDEntitlement.get_active_for_user(user_id=user.id) is not None

    async def require_practice(self, *, user: User) -> None:
        """
        Permit starting a practice set, or refuse with the reason.

        Reads only what the decision needs — the grant, then the count if there is no grant —
        rather than assembling the full access state the endpoints return.

        Args:
            user: The caller.

        Raises:
            EntitlementRequired: The free practice allowance is used up.
        """
        logging.info("Executing EntitlementService.require_practice")
        if await self.has_paid_access(user=user):
            return

        used = await self.CRUDSession.count_practice_sets_answered(user_id=user.id)
        limit = settings.FREE_PRACTICE_SESSIONS
        if used >= limit:
            logging.warning(f"User {user.id} exhausted the free practice allowance")
            track(
                event=AnalyticsEvent.PAYWALL_REACHED,
                user_id=user.id,
                properties={"reason": "practice_limit_reached", "used": used, "limit": limit},
            )
            raise EntitlementRequired(
                reason="practice_limit_reached",
                message=(
                    f"You have used all {limit} free practice sets. Upgrade for unlimited "
                    "adaptive practice."
                ),
                used=used,
                limit=limit,
            )

    async def require_grading(self, *, user: User, session_type: str) -> None:
        """
        Permit grading one more answer, or refuse with the reason.

        Checked before the answer is persisted rather than after, because the limit exists to
        bound spending on model calls and an attempt that is stored but never graded is worse
        than a clear refusal — it looks to the student like an answer that was swallowed.

        Diagnostic answers bypass the cap entirely, and are checked for that first so the free
        assessment costs no queries at all: the free diagnostic is graded in full, by the same
        path as paid practice, or the results it produces would not be evidence of anything.

        Args:
            user: The caller.
            session_type: Which kind of session the answer belongs to.

        Raises:
            EntitlementRequired: Today's free grading allowance is used up.
        """
        logging.info("Executing EntitlementService.require_grading")
        if session_type == SessionType.DIAGNOSTIC:
            return
        if await self.has_paid_access(user=user):
            return

        window_start = datetime.now(UTC) - timedelta(hours=GRADING_WINDOW_HOURS)
        used = await self.CRUDAttempt.count_graded_since(user_id=user.id, since=window_start)
        limit = settings.FREE_DAILY_GRADED_ATTEMPTS
        if used >= limit:
            logging.warning(f"User {user.id} exhausted the daily free grading allowance")
            track(
                event=AnalyticsEvent.PAYWALL_REACHED,
                user_id=user.id,
                properties={"reason": "grading_limit_reached", "used": used, "limit": limit},
            )
            raise EntitlementRequired(
                reason="grading_limit_reached",
                message=(
                    f"You have used all {limit} graded answers for today. Upgrade for unlimited "
                    "grading, or come back tomorrow."
                ),
                used=used,
                limit=limit,
            )

    async def require_new_diagnostic(self, *, user: User) -> None:
        """
        Permit composing a second diagnostic, or refuse with the reason.

        Only reached when the caller has no diagnostic to resume or return to, so a student who
        reloads mid-sitting or revisits their results is never refused by this.

        Args:
            user: The caller.

        Raises:
            EntitlementRequired: A free account has already used its one diagnostic.
        """
        logging.info("Executing EntitlementService.require_new_diagnostic")
        if await self.has_paid_access(user=user):
            return

        taken = await self.CRUDSession.count_by_type(
            user_id=user.id, session_type=SessionType.DIAGNOSTIC
        )
        if taken >= FREE_DIAGNOSTICS:
            logging.warning(f"User {user.id} requested a second diagnostic on the free tier")
            track(
                event=AnalyticsEvent.PAYWALL_REACHED,
                user_id=user.id,
                properties={
                    "reason": "diagnostic_limit_reached",
                    "used": taken,
                    "limit": FREE_DIAGNOSTICS,
                },
            )
            raise EntitlementRequired(
                reason="diagnostic_limit_reached",
                message=(
                    "Your free diagnostic has already been taken. Upgrade to sit another and "
                    "measure how far you have moved."
                ),
                used=taken,
                limit=FREE_DIAGNOSTICS,
            )
