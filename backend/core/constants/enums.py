"""Domain enumerations shared by models, schemas, and business logic.

These are stored as text with a database CHECK constraint rather than as PostgreSQL ENUM types:
adding or retiring a value then needs only a constraint change, not an `ALTER TYPE` that cannot
be rolled back cleanly. The Python enum gives type safety in application code, and the CHECK
gives integrity in the database.
"""

from enum import StrEnum


class UserStatus(StrEnum):
    """Account lifecycle state. Only ACTIVE accounts may authenticate."""

    ACTIVE = "active"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class TargetRole(StrEnum):
    """Recruiting track the student is preparing for."""

    IB = "ib"
    PE = "pe"
    BOTH = "both"


class QuestionStatus(StrEnum):
    """Question lifecycle. Only ACTIVE questions may be selected into new sessions."""

    DRAFT = "draft"
    ACTIVE = "active"
    RETIRED = "retired"


class QuestionVersionStatus(StrEnum):
    """Version lifecycle. Exactly one PUBLISHED version may exist per question."""

    DRAFT = "draft"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"


class SessionType(StrEnum):
    """Kind of practice session. Diagnostic composition is fixed; practice is adaptive."""

    DIAGNOSTIC = "diagnostic"
    PRACTICE = "practice"


class SessionStatus(StrEnum):
    """Session lifecycle state."""

    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class GradingStatus(StrEnum):
    """Attempt grading state machine.

    PENDING → GRADING → GRADED on success; GRADING → FAILED when the provider could not produce a
    valid result. A FAILED attempt never carries a score: a grading failure must not be
    indistinguishable from a genuinely poor answer.
    """

    PENDING = "pending"
    GRADING = "grading"
    GRADED = "graded"
    FAILED = "failed"


class Band(StrEnum):
    """Qualitative grade band shown alongside the numeric score."""

    STRONG = "strong"
    DEVELOPING = "developing"
    NEEDS_WORK = "needs_work"


class ValidationStatus(StrEnum):
    """Outcome of validating a provider response against the expected grade schema."""

    VALID = "valid"
    INVALID_SCHEMA = "invalid_schema"
    INVALID_VALUES = "invalid_values"
    PROVIDER_ERROR = "provider_error"
    TIMEOUT = "timeout"


class Plan(StrEnum):
    """Billing plan. FREE is the absence of a paid subscription, not a purchased plan."""

    FREE = "free"
    PRO_MONTHLY = "pro_monthly"
    SEASON_PASS = "season_pass"  # noqa: S105 — a plan name, not a credential


class SubscriptionStatus(StrEnum):
    """Mirror of the payment provider's subscription state."""

    ACTIVE = "active"
    TRIALING = "trialing"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    INCOMPLETE = "incomplete"
    EXPIRED = "expired"


class Entitlement(StrEnum):
    """Server-authoritative paid access grant.

    Free access is represented by having no active entitlement row, never by an entitlement
    value, so the access check is 'does an active grant exist' rather than a value comparison.
    """

    PRO = "pro"
    SEASON_PASS = "season_pass"  # noqa: S105 — a plan name, not a credential


class EntitlementStatus(StrEnum):
    """Entitlement lifecycle state."""

    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class BillingEventStatus(StrEnum):
    """Processing state of a received payment-provider event.

    IGNORED is deliberately distinct from PROCESSED: most Stripe event types are of no interest
    to this application, and recording them as processed would hide the difference between "we
    acted on this" and "we deliberately did not".
    """

    RECEIVED = "received"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"


class GradeFlagReason(StrEnum):
    """Why a student disputed a grade."""

    SCORE_TOO_LOW = "score_too_low"
    SCORE_TOO_HIGH = "score_too_high"
    WRONG_CONCEPTS = "wrong_concepts"
    UNCLEAR_FEEDBACK = "unclear_feedback"
    OTHER = "other"


class GradeFlagStatus(StrEnum):
    """Admin review state of a disputed grade."""

    OPEN = "open"
    REVIEWING = "reviewing"
    RESOLVED = "resolved"
    REJECTED = "rejected"


def values(enum_class: type[StrEnum]) -> list[str]:
    """
    Return an enum's values as plain strings for database CHECK constraints.

    Keeps the constraint definition tied to the enum, so adding a member cannot leave the
    database constraint silently out of date.

    Args:
        enum_class: The StrEnum subclass to expand.

    Returns:
        list[str]: Every member value, in declaration order.
    """
    return [member.value for member in enum_class]


def in_check(column: str, enum_class: type[StrEnum], nullable: bool = False) -> str:
    """
    Build a SQL ``IN`` predicate restricting a column to an enum's values.

    Generating the predicate from the enum keeps the database CHECK constraint from drifting out
    of date when a member is added or removed.

    Args:
        column: Column name the constraint applies to.
        enum_class: StrEnum subclass whose values are permitted.
        nullable: When True, NULL is also permitted.

    Returns:
        str: SQL predicate suitable for a CheckConstraint.
    """
    allowed = ", ".join(repr(value) for value in values(enum_class))
    predicate = f"{column} IN ({allowed})"
    return f"{column} IS NULL OR {predicate}" if nullable else predicate
