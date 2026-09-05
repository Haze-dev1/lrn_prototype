"""Response schemas for plans, entitlements and checkout.

These shapes are the enforcement point for one rule: the browser is told what access it has, and
is never told anything it could use to grant itself more. There is no writable field here, and
no secret — a price ID, a customer ID and a subscription ID all stay on the server, because a
client that knows them can do nothing useful with them but a leaked one is an identifier for a
real person's payment record.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from core.constants.enums import Plan


class PlanResponse(BaseModel):
    """One purchasable (or current) plan, as the pricing page renders it."""

    plan: Plan
    name: str
    tagline: str
    features: list[str]
    #: False when the plan has no configured price. Shown as unavailable rather than offered and
    #: then failing at checkout.
    purchasable: bool
    #: True for a one-time purchase, which the interface presents differently from a subscription.
    one_time: bool
    duration_days: int | None = None


class FreeTierUsageResponse(BaseModel):
    """What a free account has used, and what is left.

    Returned to paid accounts too, with the same numbers. The interface decides whether to show
    it; the API does not pretend the counters stop existing when someone pays.
    """

    diagnostics_taken: int
    practice_sessions_used: int
    practice_sessions_limit: int
    practice_sessions_remaining: int
    graded_last_24h: int
    daily_grade_limit: int
    grades_remaining_today: int


class EntitlementResponse(BaseModel):
    """The caller's current access. The single source the interface reads to decide what to show."""

    plan: Plan
    is_paid: bool
    #: Access end date. Null for an active subscription, which has no end until it is cancelled.
    active_until: datetime | None = None
    #: When access last ended, for a lapsed Season Pass or a subscription that has run out.
    expired_at: datetime | None = None
    #: True when a subscription is set to stop at the end of the paid period.
    cancel_at_period_end: bool = False
    #: Whether the Customer Portal can be opened — it needs a provider customer to open it for.
    can_manage_billing: bool = False
    can_start_practice: bool
    can_grade_answer: bool
    can_start_new_diagnostic: bool
    usage: FreeTierUsageResponse


class PlansResponse(BaseModel):
    """The plan catalogue, and where the caller currently sits in it."""

    plans: list[PlanResponse]
    #: Null for an anonymous visitor: the pricing page is public.
    entitlement: EntitlementResponse | None = None
    #: False when payments are not configured in this deployment. The interface says so rather
    #: than offering a button that cannot work.
    billing_enabled: bool = Field(description="Whether checkout can currently be started.")


class CheckoutResponse(BaseModel):
    """Where to send the browser to pay."""

    url: str


class PortalResponse(BaseModel):
    """Where to send the browser to manage billing."""

    url: str
