"""The payment provider boundary.

Everything above this line deals in the types declared here: a checkout link, a portal link, a
verified event, a normalised subscription. Nothing above it imports ``stripe``, knows what a
price ID looks like, or reads a provider object's field names. Swapping Stripe for another
processor should touch exactly one implementation file.

Deliberately narrow. The provider creates links, verifies signatures and reads back provider
state; it decides nothing about access. Whether a verified payment becomes an entitlement is a
business decision, and it belongs above this boundary where it can be reasoned about and tested
without a payment processor.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class PaymentError(Exception):
    """A payment provider call could not be completed."""


class PaymentConfigurationError(PaymentError):
    """The provider is not configured well enough to do what was asked."""


class SignatureVerificationFailed(PaymentError):
    """A webhook payload did not carry a valid signature for the configured secret.

    Its own type because it is the one provider failure that is never retried and never logged as
    a system error: an unverified event is an anonymous POST claiming a payment happened, and the
    correct response is to reject it.
    """


@dataclass(frozen=True)
class CheckoutLink:
    """A hosted checkout session the browser is sent to."""

    session_id: str
    url: str


@dataclass(frozen=True)
class ProviderEvent:
    """A webhook event whose signature has been verified.

    ``payload`` is the provider's own object graph and is treated as untrusted structure — it is
    read through explicit lookups, never spread into a model — but its authenticity is
    established: it is only constructed after signature verification succeeds.
    """

    event_id: str
    event_type: str
    created_at: datetime | None
    payload: dict[str, Any]


@dataclass(frozen=True)
class ProviderSubscription:
    """A provider subscription, normalised into this application's vocabulary.

    ``status`` is already mapped to ``SubscriptionStatus``, so no caller has to know that Stripe
    calls a lapsed subscription ``unpaid`` or that ``incomplete_expired`` exists at all.
    """

    provider_subscription_id: str
    provider_customer_id: str | None
    status: str
    price_id: str | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    metadata: dict[str, str] = field(default_factory=dict)


class PaymentProvider(ABC):
    """Creates payment links, verifies events, and reads back provider state."""

    #: Stable identifier stored on every subscription, entitlement and billing event.
    name: str

    @abstractmethod
    async def create_checkout_link(
        self,
        *,
        price_id: str,
        mode: str,
        client_reference_id: str,
        customer_email: str | None,
        customer_id: str | None,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
    ) -> CheckoutLink:
        """
        Create a hosted checkout session and return the link to send the browser to.

        Args:
            price_id: Provider price to charge.
            mode: Provider checkout mode, from the plan definition.
            client_reference_id: This application's user ID, echoed back on the event.
            customer_email: Prefills checkout; ignored when a customer already exists.
            customer_id: Existing provider customer, so a repeat purchase reuses one record.
            success_url: Where checkout returns on success.
            cancel_url: Where checkout returns when abandoned.
            metadata: Application metadata attached to the session and its objects.

        Returns:
            CheckoutLink: Session identifier and hosted URL.

        Raises:
            PaymentError: If the session could not be created.
        """

    @abstractmethod
    async def create_portal_link(self, *, customer_id: str, return_url: str) -> str:
        """
        Create a customer portal session for managing or cancelling a subscription.

        Args:
            customer_id: The provider customer to open the portal for.
            return_url: Where the portal returns the user to.

        Returns:
            str: Hosted portal URL.

        Raises:
            PaymentError: If the session could not be created.
        """

    @abstractmethod
    def verify_event(self, *, payload: bytes, signature: str | None) -> ProviderEvent:
        """
        Verify a webhook payload's signature and parse it.

        Takes raw bytes rather than a parsed body on purpose: the signature covers the exact bytes
        sent, and re-serialising a parsed payload changes them.

        Args:
            payload: Exact request body as received.
            signature: The provider's signature header.

        Returns:
            ProviderEvent: The verified event.

        Raises:
            SignatureVerificationFailed: The signature is missing, malformed or wrong.
            PaymentConfigurationError: No signing secret is configured.
        """

    @abstractmethod
    async def fetch_subscription(self, *, subscription_id: str) -> ProviderSubscription:
        """
        Read a subscription's current state from the provider.

        Used by reconciliation, which exists because a webhook that is never delivered leaves
        this application's mirror permanently stale.

        Args:
            subscription_id: Provider subscription identifier.

        Returns:
            ProviderSubscription: Normalised subscription state.

        Raises:
            PaymentError: If the subscription could not be read.
        """


def get_payment_provider() -> PaymentProvider:
    """
    Build the configured payment provider.

    There is exactly one, and deliberately no fake counterpart to the grading provider's. A fake
    grader produces a score that is obviously local; a fake payment provider would produce paid
    access that is indistinguishable from bought access, and the one rule this area cannot bend is
    that entitlements come only from verified payment events. Local development uses Stripe's own
    test mode, which is free and produces real, verifiable events.

    Returns:
        PaymentProvider: The configured provider.
    """
    from core.services.billing.stripe_provider import StripeProvider

    return StripeProvider()
