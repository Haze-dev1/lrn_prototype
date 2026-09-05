"""The plan catalogue: what LRN sells, and what each purchase grants.

One module maps a plan to its price, its checkout mode and the entitlement it produces, so
adding or repricing a plan is a change here rather than a hunt through controllers. Price IDs
come from configuration and are never hard-coded: they differ between Stripe's test and live
modes, and a hard-coded one would be a production checkout pointing at a test price.
"""

from dataclasses import dataclass

from core.config.settings import settings
from core.constants.enums import Entitlement, Plan


@dataclass(frozen=True)
class PlanDefinition:
    """A purchasable plan and the access it grants.

    ``duration_days`` is what separates the two paid shapes. A subscription grants open-ended
    access that lasts while the subscription stays active, so its entitlement has no end date and
    is revoked by a cancellation event. A Season Pass is bought once for a fixed window, so its
    entitlement carries a concrete end date from the moment it is granted — nothing has to
    remember to expire it later.
    """

    plan: Plan
    name: str
    tagline: str
    entitlement: Entitlement | None
    # Stripe's checkout mode. "subscription" bills recurrently; "payment" charges once.
    checkout_mode: str | None
    # None means access lasts while the subscription is active.
    duration_days: int | None
    features: tuple[str, ...]

    @property
    def price_id(self) -> str | None:
        """
        Resolve the configured Stripe price for this plan.

        Read at call time rather than stored on the dataclass so a settings override in a test —
        or a redeployment with new price IDs — is picked up without rebuilding the catalogue.

        Returns:
            str | None: The configured price ID, or None for the free plan and unconfigured ones.
        """
        if self.plan is Plan.PRO_MONTHLY:
            return settings.STRIPE_PRICE_PRO_MONTHLY
        if self.plan is Plan.SEASON_PASS:
            return settings.STRIPE_PRICE_SEASON_PASS
        return None

    @property
    def purchasable(self) -> bool:
        """
        Report whether this plan can actually be bought right now.

        A plan with no configured price is shown as unavailable rather than offered and then
        failing at checkout, which is the difference between an honest interface and a broken one.

        Returns:
            bool: True when the plan has a configured price.
        """
        return bool(self.price_id)


FREE_PLAN = PlanDefinition(
    plan=Plan.FREE,
    name="Free",
    tagline="Find out where you stand.",
    entitlement=None,
    checkout_mode=None,
    duration_days=None,
    features=(
        "The full 24-question diagnostic, graded",
        "Category mastery and your weakest area",
        f"{settings.FREE_PRACTICE_SESSIONS} practice sets",
        "Review every answer you have given",
    ),
)

PRO_MONTHLY_PLAN = PlanDefinition(
    plan=Plan.PRO_MONTHLY,
    name="Pro",
    tagline="Close the gaps, month by month.",
    entitlement=Entitlement.PRO,
    checkout_mode="subscription",
    duration_days=None,
    features=(
        "Unlimited adaptive practice",
        "Spaced repetition of everything you missed",
        "Full review history and mastery trend",
        "Cancel any time",
    ),
)

SEASON_PASS_PLAN = PlanDefinition(
    plan=Plan.SEASON_PASS,
    name="Season Pass",
    tagline="One recruiting season. One payment.",
    entitlement=Entitlement.SEASON_PASS,
    checkout_mode="payment",
    duration_days=settings.SEASON_PASS_DAYS,
    features=(
        "Everything in Pro",
        f"{settings.SEASON_PASS_DAYS} days of access from purchase",
        "No subscription to remember to cancel",
        "Priced for one recruiting cycle",
    ),
)

# Ordered as the pricing page reads: what you already have, then the two ways to upgrade.
PLANS: tuple[PlanDefinition, ...] = (FREE_PLAN, PRO_MONTHLY_PLAN, SEASON_PASS_PLAN)

PURCHASABLE_PLANS: tuple[PlanDefinition, ...] = (PRO_MONTHLY_PLAN, SEASON_PASS_PLAN)

_BY_PLAN = {definition.plan: definition for definition in PLANS}
_BY_ENTITLEMENT = {
    definition.entitlement: definition for definition in PLANS if definition.entitlement
}


def get_plan(plan: str) -> PlanDefinition | None:
    """
    Look up a plan definition by its identifier.

    Args:
        plan: Plan identifier from a request or a stored subscription.

    Returns:
        PlanDefinition | None: The definition, or None when the identifier is unknown.
    """
    try:
        return _BY_PLAN[Plan(plan)]
    except ValueError:
        return None


def plan_for_entitlement(entitlement: str) -> PlanDefinition | None:
    """
    Find the plan that grants a given entitlement.

    Used to describe a user's current access in the language of what they bought, rather than in
    the internal entitlement name.

    Args:
        entitlement: Entitlement identifier held by the user.

    Returns:
        PlanDefinition | None: The granting plan, or None when the value is unknown.
    """
    try:
        return _BY_ENTITLEMENT.get(Entitlement(entitlement))
    except ValueError:
        return None
