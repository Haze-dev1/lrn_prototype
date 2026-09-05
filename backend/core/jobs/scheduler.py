"""APScheduler setup for recurring background work.

Job business logic lives in domain services and is invoked from here, so the same functions can
be called from an API request or a scheduled run.
"""

from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from commons.redis_client import get_redis
from core import logger
from core.jobs.locks import job_lock
from core.services.ai.grading_service import GradingService
from core.services.analytics.retention_service import RetentionService
from core.services.billing.reconciliation_service import ReconciliationService
from core.services.email.email_service import EmailService
from core.services.mastery.service import MasteryService

logging = logger(__name__)

HEARTBEAT_KEY = "lrn:scheduler:heartbeat"
HEARTBEAT_INTERVAL_SECONDS = 30
# Longer than the interval so a single slow tick does not mark a working scheduler unhealthy,
# short enough that a dead scheduler is detected within roughly two intervals.
HEARTBEAT_TTL_SECONDS = 90

# A student is waiting on a stranded grade, so the sweep runs on a minute scale rather than an
# hourly one. The attempt age filter, not this interval, is what stops it colliding with grading
# still in flight.
GRADING_RETRY_INTERVAL_SECONDS = 60
# Comfortably longer than a full sweep of grading calls, so a replica that dies mid-sweep does
# not block the job until the next process restart.
GRADING_RETRY_LOCK_TTL_SECONDS = 900

# Reconciliation repairs webhook deliveries that never arrived. Hourly rather than nightly:
# the window between a cancellation and this sweep is the window in which someone who stopped
# paying still has access, and a day of that is worse than twenty-four cheap sweeps.
ENTITLEMENT_RECONCILE_INTERVAL_SECONDS = 3600
ENTITLEMENT_RECONCILE_LOCK_TTL_SECONDS = 1800

# A student who has just finished a 24-question diagnostic is waiting for the email, so this
# runs on a minute scale. The sweep only selects sessions whose grading has fully resolved,
# which is what stops it mailing a score computed from half the answers.
RESULTS_EMAIL_INTERVAL_SECONDS = 120
RESULTS_EMAIL_LOCK_TTL_SECONDS = 600
# Long enough to outlast a full pass over every eligible student.
NUDGE_LOCK_TTL_SECONDS = 1800
RETENTION_LOCK_TTL_SECONDS = 900


async def heartbeat_job() -> None:
    """
    Publish a liveness marker for the scheduler process.

    Writes an expiring key so the container health check can distinguish a scheduler that is
    running its job loop from one whose process is alive but whose scheduler has stalled. This is
    intentionally not lock-guarded: every replica must prove its own liveness.
    """
    try:
        await get_redis().set(
            HEARTBEAT_KEY,
            datetime.now(UTC).isoformat(),
            ex=HEARTBEAT_TTL_SECONDS,
        )
    except Exception as error:
        logging.error(f"Error in heartbeat_job: {error}")


async def mastery_rollup_job() -> None:
    """
    Recompute mastery scores for every user with recent graded activity.

    Runs nightly so dashboard and recommendation reads stay cheap and consistent. Lock-guarded so
    exactly one scheduler replica performs the roll-up per window; idempotent, so a retry after a
    partial failure recomputes the same scores rather than compounding them.
    """
    async with job_lock("mastery_rollup", ttl_seconds=3600) as acquired:
        if not acquired:
            return
        logging.info("Executing mastery_rollup_job")
        try:
            recalculated = await MasteryService().recalculate_recently_active()
            logging.info(f"mastery_rollup_job recalculated {recalculated} users")
        except Exception as error:
            logging.error(f"Error in mastery_rollup_job: {error}")


async def grading_retry_job() -> None:
    """
    Finish grading for answers whose grading never resolved.

    This is what makes "an answer is never lost to an AI failure" true rather than aspirational.
    Grading normally runs as a background task in the submitting request's process, so a deploy,
    a crash, or a container restart between persisting an answer and writing its grade would
    otherwise strand that attempt forever with no one looking at it.

    Runs often because a student is waiting on the result, and is lock-guarded so replicas do not
    grade the same answer twice at double the cost. Idempotent: an attempt that reached GRADED
    between the sweep selecting it and processing it is skipped rather than re-graded, so a
    student never sees a grade they have already read change underneath them.
    """
    async with job_lock("grading_retry", ttl_seconds=GRADING_RETRY_LOCK_TTL_SECONDS) as acquired:
        if not acquired:
            return
        try:
            summary = await GradingService().retry_unresolved()
            if summary["examined"]:
                logging.info(f"grading_retry_job processed {summary}")
        except Exception as error:
            logging.error(f"Error in grading_retry_job: {error}")


async def entitlement_reconciliation_job() -> None:
    """
    Bring billing state back in line with the payment provider.

    The durability guarantee behind entitlements, in the same way the grading sweep is the one
    behind answers. A webhook that exhausts its retries while this application is down is never
    delivered again, and nothing inside the webhook handler can recover from that — only asking
    the provider what is true can.

    Lock-guarded so replicas do not both re-check every subscription, and idempotent: a sweep that
    finds nothing wrong writes nothing.
    """
    async with job_lock(
        "entitlement_reconciliation", ttl_seconds=ENTITLEMENT_RECONCILE_LOCK_TTL_SECONDS
    ) as acquired:
        if not acquired:
            return
        try:
            summary = await ReconciliationService().run()
            if summary["corrected"] or summary["expired"] or summary["failed"]:
                logging.info(f"entitlement_reconciliation_job processed {summary}")
        except Exception as error:
            logging.error(f"Error in entitlement_reconciliation_job: {error}")


async def diagnostic_results_email_job() -> None:
    """
    Mail the results of every diagnostic that has finished grading and not been mailed.

    A sweep rather than a send at completion time, because grading is asynchronous: when a student
    submits their last answer, none of it may be graded yet. Driving from stored state also means
    a crash or a deploy between finishing and sending costs a delay rather than the email.

    Lock-guarded so replicas do not both mail the same student, and idempotent: the send marker is
    written only after the provider accepts, so a failure is retried and a success never repeats.
    """
    async with job_lock("diagnostic_results_email", ttl_seconds=RESULTS_EMAIL_LOCK_TTL_SECONDS) as (
        acquired
    ):
        if not acquired:
            return
        try:
            summary = await EmailService().deliver_pending_diagnostic_results()
            if summary["examined"]:
                logging.info(f"diagnostic_results_email_job processed {summary}")
        except Exception as error:
            logging.error(f"Error in diagnostic_results_email_job: {error}")


async def weekly_nudge_email_job() -> None:
    """
    Send the weak-area nudge to every student who is due one and has something to be nudged about.

    The weekly cadence is the schedule; the guarantee is the per-recipient interval checked in the
    query, so a re-run, a backfill or a second replica cannot double-send. Every message carries a
    one-click unsubscribe, and a student who has turned reminders off is excluded by the query
    rather than filtered afterwards.
    """
    async with job_lock("weekly_nudge_email", ttl_seconds=NUDGE_LOCK_TTL_SECONDS) as acquired:
        if not acquired:
            return
        try:
            summary = await EmailService().send_weekly_nudges()
            if summary["examined"]:
                logging.info(f"weekly_nudge_email_job processed {summary}")
        except Exception as error:
            logging.error(f"Error in weekly_nudge_email_job: {error}")


async def retention_events_job() -> None:
    """
    Emit week-2 and week-4 return events for students who came back inside a window.

    Retention is a window being entered, which no single request knows it is the first of — so it
    is detected by a sweep. Deduped in Redis, where a lost key costs one duplicated point on a
    chart and nothing else.
    """
    async with job_lock("retention_events", ttl_seconds=RETENTION_LOCK_TTL_SECONDS) as acquired:
        if not acquired:
            return
        try:
            await RetentionService().run()
        except Exception as error:
            logging.error(f"Error in retention_events_job: {error}")


def build_scheduler() -> AsyncIOScheduler:
    """
    Create the application scheduler with its registered jobs.

    ``coalesce`` collapses runs missed during downtime into a single execution, and
    ``max_instances=1`` stops a slow job overlapping itself within one process; the Redis lock
    provides the same guarantee across processes.

    Returns:
        AsyncIOScheduler: Configured, not-yet-started scheduler.
    """
    logging.info("Executing build_scheduler")
    scheduler = AsyncIOScheduler(
        timezone="UTC",
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 300},
    )

    scheduler.add_job(
        heartbeat_job,
        trigger=IntervalTrigger(seconds=HEARTBEAT_INTERVAL_SECONDS),
        id="scheduler_heartbeat",
        next_run_time=datetime.now(UTC),
        replace_existing=True,
    )
    # 02:30 UTC: after the day's activity has settled and before European morning traffic.
    scheduler.add_job(
        mastery_rollup_job,
        trigger=CronTrigger(hour=2, minute=30),
        id="mastery_rollup",
        replace_existing=True,
    )
    scheduler.add_job(
        grading_retry_job,
        trigger=IntervalTrigger(seconds=GRADING_RETRY_INTERVAL_SECONDS),
        id="grading_retry",
        replace_existing=True,
    )
    scheduler.add_job(
        entitlement_reconciliation_job,
        trigger=IntervalTrigger(seconds=ENTITLEMENT_RECONCILE_INTERVAL_SECONDS),
        id="entitlement_reconciliation",
        replace_existing=True,
    )
    scheduler.add_job(
        diagnostic_results_email_job,
        trigger=IntervalTrigger(seconds=RESULTS_EMAIL_INTERVAL_SECONDS),
        id="diagnostic_results_email",
        replace_existing=True,
    )
    # Monday 09:00 UTC: a study reminder is worth sending at the start of a working week, and
    # early enough that it is still near the top of the inbox when the reader opens it.
    scheduler.add_job(
        weekly_nudge_email_job,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="weekly_nudge_email",
        replace_existing=True,
    )
    # 03:15 UTC, after the mastery rollup: retention is read from graded activity, and running it
    # in the same quiet window keeps both off the daytime path.
    scheduler.add_job(
        retention_events_job,
        trigger=CronTrigger(hour=3, minute=15),
        id="retention_events",
        replace_existing=True,
    )

    return scheduler
