"""The analytics vocabulary: what may be recorded, and what may be attached to it.

Two allowlists, and both of them are the point of this module.

``AnalyticsEvent`` fixes the event names. Analytics decays when the same action is recorded under
three spellings across two years, and a funnel built on ``diagnostic_completed`` silently breaks
the day someone writes ``diagnostic_complete``. Naming them here makes that a type error.

``SAFE_PROPERTY_KEYS`` fixes what may travel with an event. The product's rule is that raw student
answer content never reaches general analytics, and the reliable way to hold that line is an
allowlist rather than a blocklist: a blocklist has to anticipate every name someone might give an
answer field, and it only has to be wrong once. Anything not named here is dropped before it
leaves the process.
"""

from enum import StrEnum


class AnalyticsEvent(StrEnum):
    """Every event this product records.

    The first block is the funnel, in order. A student who signs up, sits the diagnostic, reads
    their results, upgrades and practises passes through all of them exactly once each, which is
    what makes drop-off between any two of them readable.
    """

    LANDING_VIEW = "landing_view"
    USER_SIGNED_UP = "user_signed_up"
    DIAGNOSTIC_STARTED = "diagnostic_started"
    DIAGNOSTIC_COMPLETED = "diagnostic_completed"
    RESULTS_VIEWED = "results_viewed"
    CHECKOUT_STARTED = "checkout_started"
    CHECKOUT_COMPLETED = "checkout_completed"
    PRACTICE_STARTED = "practice_started"
    PRACTICE_COMPLETED = "practice_completed"
    ANSWER_SUBMITTED = "answer_submitted"
    GRADE_RECEIVED = "grade_received"

    # Engagement and quality signals that sit outside the funnel.
    REVIEW_OPENED = "review_opened"
    GRADE_FLAGGED = "grade_flagged"
    MASTERY_IMPROVED = "mastery_improved"
    PAYWALL_REACHED = "paywall_reached"

    # Retention. Emitted by a scheduled sweep when the window is entered, not on every visit.
    WEEK_2_RETURN = "week_2_return"
    WEEK_4_RETURN = "week_4_return"


#: Events an unauthenticated browser may report through the public endpoint.
#:
#: Deliberately tiny. Everything else in the funnel happens server-side, where the event is a
#: consequence of work the API actually did — and an event a client can assert is an event a
#: client can fabricate. Letting a browser claim ``checkout_completed`` would corrupt the single
#: number this product is measured on.
PUBLIC_EVENTS: frozenset[str] = frozenset(
    {
        AnalyticsEvent.LANDING_VIEW,
        AnalyticsEvent.PAYWALL_REACHED,
    }
)


#: Property names permitted on any event.
#:
#: Every one is a scalar describing *what happened*, never *what was written*. There is no key
#: here for an answer, a prompt, feedback, an ideal answer, or a concept label — because the
#: moment one exists, someone fills it in.
SAFE_PROPERTY_KEYS: frozenset[str] = frozenset(
    {
        # What the event was about, by identifier only.
        "session_id",
        "session_type",
        "attempt_id",
        "question_id",
        "category_slug",
        "difficulty",
        # Outcomes, as numbers and fixed vocabularies.
        "score",
        "band",
        "overall_score",
        "previous_score",
        "delta",
        "concepts_hit_count",
        "concepts_missed_count",
        "grading_status",
        "validation_status",
        # Shape of the thing, not its content.
        "question_count",
        "requested_size",
        "measured_categories",
        "evidence_count",
        "review_due_count",
        "answered_count",
        "graded_count",
        "failed_count",
        # Billing and access.
        "plan",
        "entitlement",
        "is_paid",
        "reason",
        "limit",
        "used",
        # Provenance and timing.
        "provider",
        "model",
        "prompt_version",
        "latency_ms",
        "retry_count",
        "days_since_signup",
        "source",
        "surface",
        "filtered",
    }
)

#: Longest string a property value may be. Anything longer is a body of text rather than a label,
#: and a body of text in an analytics property is how answer content escapes in practice.
MAX_PROPERTY_LENGTH = 120
