"""Request schemas for billing."""

from pydantic import BaseModel, Field

from core.constants.enums import Plan


class CheckoutRequest(BaseModel):
    """Payload starting a hosted checkout.

    The plan is the *only* thing the client sends. There is no price, no amount, no currency and
    no duration: every one of those is resolved server-side from the plan catalogue, so a client
    cannot ask to be charged its own number or granted its own window.
    """

    plan: Plan = Field(description="Plan to purchase. Free is not purchasable.")
