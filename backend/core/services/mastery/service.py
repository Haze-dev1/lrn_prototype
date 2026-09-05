"""Mastery score calculation.

Mastery answers "how ready am I in this category" from graded evidence alone. The calculation is
deliberately simple and explainable: a recency-weighted mean of past scores. A student who asks
why their Valuation score moved must be able to get a real answer, which rules out anything whose
behaviour cannot be described in a sentence.

The weighting is configuration, not product truth. It is stated here in one place so it can be
tuned against real usage rather than being scattered through the code that consumes it.
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from core import logger
from core.cruds.attempt_crud import CRUDAttempt
from core.cruds.skill_score_crud import CRUDSkillScore
from core.models.skill_score_model import SkillScore
from core.services.analytics.events import AnalyticsEvent
from core.services.analytics.service import track

logging = logger(__name__)

# Days after which an attempt counts half as much as a fresh one. Thirty days roughly matches a
# recruiting-season study cycle: work from last month still counts, but this week's work moves
# the number.
RECENCY_HALF_LIFE_DAYS = 30.0

# Attempts older than this are dropped entirely. Without a floor, a strong performance from a
# year ago would keep propping up a category the student has since stopped practising.
EVIDENCE_WINDOW_DAYS = 365

# Categories below this many graded attempts are still scored, but the caller can use the
# evidence count to present the score as provisional rather than settled.
CONFIDENT_EVIDENCE_THRESHOLD = 3


def calculate_weighted_score(
    scored_attempts: list[tuple[int, datetime]], *, now: datetime | None = None
) -> int | None:
    """
    Compute a recency-weighted mastery score from graded attempts.

    Each attempt's weight halves every ``RECENCY_HALF_LIFE_DAYS``, so recent work dominates while
    older evidence still contributes. Returns None rather than zero when there is no evidence:
    "not measured yet" and "measured as bad" are different claims, and showing the second when
    the first is true would be a fabricated readiness signal.

    Args:
        scored_attempts: (score, graded_at) pairs for one category.
        now: Reference time for age calculation; defaults to the current time.

    Returns:
        int | None: Mastery score 0-100, or None when there is no usable evidence.
    """
    reference = now or datetime.now(UTC)
    cutoff = reference - timedelta(days=EVIDENCE_WINDOW_DAYS)

    weighted_total = 0.0
    weight_total = 0.0
    for score, graded_at in scored_attempts:
        if graded_at < cutoff:
            continue
        age_days = max((reference - graded_at).total_seconds() / 86400.0, 0.0)
        weight = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
        weighted_total += score * weight
        weight_total += weight

    if weight_total == 0.0:
        return None

    # Clamped because a caller supplying out-of-range scores should not be able to produce a
    # mastery value the database would then reject.
    return max(0, min(100, round(weighted_total / weight_total)))


class MasteryService:
    """Recomputes and stores per-category mastery from graded attempts."""

    def __init__(self) -> None:
        """Initialise the service with the CRUD layers it coordinates."""
        self.CRUDAttempt = CRUDAttempt()
        self.CRUDSkillScore = CRUDSkillScore()

    async def recalculate_for_user(self, *, user_id: uuid.UUID) -> list[SkillScore]:
        """
        Recompute and persist every category score for one user.

        Reads all of the user's graded evidence in a single query and groups it in memory, rather
        than issuing one query per category, so the nightly rollup costs one round trip per user
        instead of eight. Idempotent: running it twice with unchanged evidence produces the same
        scores, which is what makes the scheduled job safe to retry.

        Args:
            user_id: User whose mastery should be recomputed.

        Returns:
            list[SkillScore]: The stored score rows, weakest first.

        Raises:
            Exception: If reading evidence or writing scores fails.
        """
        try:
            logging.info("Executing MasteryService.recalculate_for_user")
            evidence = await self.CRUDAttempt.list_graded_for_mastery(user_id=user_id)
            if not evidence:
                logging.info(f"No graded evidence for user {user_id}, nothing to recalculate")
                return []

            by_category: dict[str, list[tuple[int, datetime]]] = defaultdict(list)
            for category_slug, score, graded_at in evidence:
                by_category[category_slug].append((score, graded_at))

            stored: list[SkillScore] = []
            for category_slug, attempts in by_category.items():
                weighted = calculate_weighted_score(attempts)
                if weighted is None:
                    # Every attempt in this category fell outside the evidence window. The
                    # existing score is left alone rather than being reset, so a category the
                    # student has not touched recently shows stale-but-real evidence instead of
                    # silently dropping to nothing.
                    logging.info(
                        f"All evidence for category {category_slug} is outside the window, "
                        f"leaving the stored score unchanged"
                    )
                    continue
                stored.append(
                    await self.CRUDSkillScore.upsert(
                        user_id=user_id,
                        category_slug=category_slug,
                        score=weighted,
                        evidence_count=len(attempts),
                        last_attempt_at=max(graded_at for _, graded_at in attempts),
                    )
                )

            stored.sort(key=lambda item: item.score)
            logging.info(f"Recalculated {len(stored)} category scores for user {user_id}")

            # The learning signal, and the strongest evidence that the product works at all. Only
            # a category that actually moved up is recorded: `previous_score` is written by the
            # upsert, so an unchanged recalculation — which happens on every results page read —
            # emits nothing.
            for score_row in stored:
                if (
                    score_row.previous_score is not None
                    and score_row.score > score_row.previous_score
                ):
                    track(
                        event=AnalyticsEvent.MASTERY_IMPROVED,
                        user_id=user_id,
                        properties={
                            "category_slug": score_row.category_slug,
                            "score": score_row.score,
                            "previous_score": score_row.previous_score,
                            "delta": score_row.score - score_row.previous_score,
                            "evidence_count": score_row.evidence_count,
                        },
                    )
            return stored
        except Exception as error:
            logging.error(f"Error in MasteryService.recalculate_for_user: {error}")
            raise error

    async def trend_for_user(
        self, *, user_id: uuid.UUID, weeks: int = 8, now: datetime | None = None
    ) -> list[dict[str, object]]:
        """
        Reconstruct a user's mastery at weekly points over the recent past.

        Derived from attempt history rather than stored. Mastery is already a pure function of
        (graded attempts, reference time), so the value at any past date can be recomputed by
        running the same weighting with the attempts that existed then — which means no history
        table to keep in step, no backfill for existing users, and no possibility of a stored
        trend disagreeing with the current score it ends at.

        The cost is one pass over the user's attempts per point, all in memory from a single
        query. At the volumes one student generates that is far cheaper than the schema and the
        write path a history table would need.

        Args:
            user_id: User whose trend to reconstruct.
            weeks: How many weekly points to produce, ending at the present.
            now: Reference time, injectable for testing.

        Returns:
            list[dict[str, object]]: Points oldest first, each with ``as_of``, per-category
            ``scores``, and an ``overall`` mean across measured categories.

        Raises:
            Exception: If reading evidence fails.
        """
        try:
            logging.info("Executing MasteryService.trend_for_user")
            reference = now or datetime.now(UTC)
            evidence = await self.CRUDAttempt.list_graded_for_mastery(user_id=user_id)
            if not evidence:
                return []

            points: list[dict[str, object]] = []
            for index in range(weeks - 1, -1, -1):
                as_of = reference - timedelta(weeks=index)
                by_category: dict[str, list[tuple[int, datetime]]] = defaultdict(list)
                for category_slug, score, graded_at in evidence:
                    # Only evidence that existed at this point counts. Including later attempts
                    # would draw a trend that already knows the future, which would show every
                    # student improving regardless of what they did.
                    if graded_at <= as_of:
                        by_category[category_slug].append((score, graded_at))

                scores = {
                    slug: value
                    for slug, attempts in by_category.items()
                    if (value := calculate_weighted_score(attempts, now=as_of)) is not None
                }
                points.append(
                    {
                        "as_of": as_of,
                        "scores": scores,
                        "overall": round(sum(scores.values()) / len(scores)) if scores else None,
                    }
                )
            return points
        except Exception as error:
            logging.error(f"Error in MasteryService.trend_for_user: {error}")
            raise error

    async def recalculate_recently_active(self, *, since_hours: int = 26) -> int:
        """
        Recompute mastery for every user with graded activity in a recent window.

        The default window slightly exceeds a day so a nightly run that starts late, or is retried
        after a failure, still covers the whole period since the previous successful run.

        Args:
            since_hours: Size of the activity window in hours.

        Returns:
            int: Number of users recalculated.

        Raises:
            Exception: If reading the active user list fails.
        """
        try:
            logging.info("Executing MasteryService.recalculate_recently_active")
            since = datetime.now(UTC) - timedelta(hours=since_hours)
            user_ids = await self.CRUDAttempt.list_user_ids_graded_since(since=since)

            recalculated = 0
            for user_id in user_ids:
                try:
                    await self.recalculate_for_user(user_id=user_id)
                    recalculated += 1
                except Exception as error:
                    # One user's bad data must not abort the whole nightly run.
                    logging.error(f"Failed to recalculate mastery for user {user_id}: {error}")

            logging.info(f"Recalculated mastery for {recalculated} of {len(user_ids)} users")
            return recalculated
        except Exception as error:
            logging.error(f"Error in MasteryService.recalculate_recently_active: {error}")
            raise error
