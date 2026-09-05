"""Retention detection.

Week-2 and week-4 return are the product's honest survival numbers: not "did they sign up", but
"did they come back after the novelty wore off". Both are emitted by a sweep rather than from a
request, because the thing being measured is a *window being entered*, which no single request
knows it is the first of.

Dedupe lives in Redis, not the database. That is deliberate and matches what Redis is for here: a
lost key costs one duplicate analytics event, which is a rounding error in a retention chart, and
nothing about a student's access, evidence or money depends on it. Putting it in PostgreSQL would
mean a migration and a column whose only job is to stop a chart double-counting.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from commons.redis_client import get_redis
from core import logger
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.user_crud import CRUDUser
from core.services.analytics.events import AnalyticsEvent
from core.services.analytics.service import analytics

logging = logger(__name__)

_KEY_PREFIX = "lrn:analytics:retention:"
# Comfortably longer than the widest window, so a key cannot expire while it is still preventing
# a duplicate, and short enough that the keyspace does not grow forever.
_DEDUPE_TTL_SECONDS = 90 * 86400


@dataclass(frozen=True)
class RetentionWindow:
    """One retention milestone and the age range that counts as reaching it.

    A range rather than an exact day, because activity is bursty: a student who returns on day 15
    and not on day 14 has returned in week two, and a sweep that only ever asked about day 14
    would miss them entirely.
    """

    event: AnalyticsEvent
    label: str
    min_days: int
    max_days: int


WINDOWS: tuple[RetentionWindow, ...] = (
    RetentionWindow(AnalyticsEvent.WEEK_2_RETURN, "week_2", 8, 21),
    RetentionWindow(AnalyticsEvent.WEEK_4_RETURN, "week_4", 22, 42),
)


class RetentionService:
    """Emits retention events for students who came back inside a window."""

    def __init__(self) -> None:
        """Initialise the service with the CRUD layers it reads from."""
        self.CRUDUser = CRUDUser()
        self.CRUDAttempt = CRUDAttempt()

    async def _claim(self, *, user_id: uuid.UUID, label: str) -> bool:
        """
        Claim the right to emit one retention event for one student.

        ``SET NX`` is the whole mechanism: the first caller to set the key wins, every later one
        gets False, and the key expiring long after the window closes means a student is never
        counted twice. A Redis outage makes this return True, which double-counts rather than
        under-counts — the right way round for a metric, since a missing return looks like churn.

        Args:
            user_id: The student.
            label: Which window is being claimed.

        Returns:
            bool: True when this caller should emit the event.
        """
        try:
            claimed = await get_redis().set(
                f"{_KEY_PREFIX}{label}:{user_id}", "1", ex=_DEDUPE_TTL_SECONDS, nx=True
            )
            return bool(claimed)
        except Exception as error:
            logging.warning(f"Retention dedupe unavailable, emitting anyway: {error}")
            return True

    async def run(self, *, now: datetime | None = None) -> dict[str, int]:
        """
        Emit retention events for students active inside a return window.

        Activity means a graded answer, not a page view. Someone who signs in, looks at their
        dashboard and leaves has not returned to the product in the sense this metric is measuring
        — the question is whether they came back to *practise*.

        Returns:
            dict[str, int]: How many events were emitted per window.

        Raises:
            Exception: If the underlying reads fail.
        """
        logging.info("Executing RetentionService.run")
        reference = now or datetime.now(UTC)
        emitted = dict.fromkeys((window.label for window in WINDOWS), 0)

        # One query per window rather than one per user: the widest window is six weeks, and the
        # set of users with recent graded activity is far smaller than the set of all users.
        for window in WINDOWS:
            active_ids = await self.CRUDAttempt.list_user_ids_graded_since(
                since=reference - timedelta(days=1)
            )
            for user_id in active_ids:
                user = await self.CRUDUser.get_by_id(user_id=user_id)
                if user is None:
                    continue
                age_days = (reference - user.created_at).days
                if not window.min_days <= age_days <= window.max_days:
                    continue
                if not await self._claim(user_id=user_id, label=window.label):
                    continue
                await analytics.record(
                    event=window.event,
                    user_id=user_id,
                    properties={"days_since_signup": age_days},
                )
                emitted[window.label] += 1

        if any(emitted.values()):
            logging.info(f"RetentionService.run emitted {emitted}")
        return emitted
