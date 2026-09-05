"""The Stripe adapter — the only module in the application that imports ``stripe``.

Everything Stripe-specific lives here: price IDs on line items, the shape of a checkout session,
the name of the signature header, and the mapping from Stripe's subscription statuses to this
application's. Above this file, a subscription is a ``ProviderSubscription`` and a webhook is a
``ProviderEvent``.
"""

from datetime import UTC, datetime
from typing import Any

import stripe

from core import logger
from core.config.settings import settings
from core.constants.enums import SubscriptionStatus
from core.services.billing.provider import (
    CheckoutLink,
    PaymentConfigurationError,
    PaymentError,
    PaymentProvider,
    ProviderEvent,
    ProviderSubscription,
    SignatureVerificationFailed,
)

logging = logger(__name__)

# Stripe's vocabulary is wider than this application's. ``unpaid`` and ``incomplete_expired`` both
# mean "this subscription is over" here, and collapsing them at the boundary keeps every caller
# above from having to know that. An unmapped status is treated as INCOMPLETE rather than
# defaulting to ACTIVE: a status this application does not understand must never grant access.
_STATUS_MAP: dict[str, SubscriptionStatus] = {
    "active": SubscriptionStatus.ACTIVE,
    "trialing": SubscriptionStatus.TRIALING,
    "past_due": SubscriptionStatus.PAST_DUE,
    "canceled": SubscriptionStatus.CANCELED,
    "incomplete": SubscriptionStatus.INCOMPLETE,
    "incomplete_expired": SubscriptionStatus.EXPIRED,
    "unpaid": SubscriptionStatus.EXPIRED,
    "paused": SubscriptionStatus.PAST_DUE,
}


def _timestamp(value: object) -> datetime | None:
    """
    Convert a Stripe epoch-second timestamp into an aware datetime.

    Stripe sends integers; the database stores ``timestamptz``. Anything that is not an integer —
    a missing field, a null, an expanded object — becomes None rather than raising, because a
    subscription with no period end is a valid state and not a reason to reject the event.

    Args:
        value: Raw field from a Stripe object.

    Returns:
        datetime | None: Aware UTC datetime, or None.
    """
    if isinstance(value, int) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, tz=UTC)
    return None


def _string(value: object) -> str | None:
    """
    Read a Stripe field that is either an ID string or an expanded object.

    Stripe returns ``customer`` as an ID by default and as a full object when expanded, and the
    same field can arrive either way depending on how the event was produced. Normalising here
    keeps every caller from having to check.

    Args:
        value: Raw field from a Stripe object.

    Returns:
        str | None: The identifier, or None when absent.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        identifier = value.get("id")
        return identifier if isinstance(identifier, str) else None
    return None


class StripeProvider(PaymentProvider):
    """Stripe hosted Checkout, Customer Portal, and webhook verification."""

    name = "stripe"

    def __init__(self) -> None:
        """Initialise the adapter without contacting Stripe.

        Construction must not fail on missing configuration: the webhook endpoint needs only the
        signing secret, and the plans endpoint needs neither. Each method checks the credential it
        actually requires.
        """
        self._api_key = settings.STRIPE_SECRET_KEY

    def _require_api_key(self) -> str:
        """
        Return the configured secret key, or fail with a clear reason.

        Returns:
            str: The Stripe secret key.

        Raises:
            PaymentConfigurationError: No secret key is configured.
        """
        if not self._api_key:
            raise PaymentConfigurationError("Stripe is not configured")
        return self._api_key

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
        Create a Stripe hosted Checkout session.

        The user ID travels as both ``client_reference_id`` and metadata, and the metadata is
        copied onto the resulting subscription. That redundancy is deliberate: the events that
        arrive later are not all checkout events, and a ``customer.subscription.updated`` arriving
        months afterwards must still be attributable to a user without a lookup that could fail.

        Args:
            price_id: Stripe price to charge.
            mode: ``subscription`` or ``payment``.
            client_reference_id: This application's user ID.
            customer_email: Prefills the email field for a first purchase.
            customer_id: Existing Stripe customer, reused for a repeat purchase.
            success_url: Return URL on success.
            cancel_url: Return URL when abandoned.
            metadata: Application metadata to attach.

        Returns:
            CheckoutLink: Session identifier and hosted URL.

        Raises:
            PaymentError: If Stripe rejected the request.
            PaymentConfigurationError: Stripe is not configured.
        """
        try:
            logging.info("Executing StripeProvider.create_checkout_link")
            params: dict[str, Any] = {
                "api_key": self._require_api_key(),
                "mode": mode,
                "line_items": [{"price": price_id, "quantity": 1}],
                "client_reference_id": client_reference_id,
                "success_url": success_url,
                "cancel_url": cancel_url,
                "metadata": metadata,
                # Stripe rejects a session that sets both, so an existing customer wins: reusing
                # the customer keeps one billing record per user instead of one per purchase.
                **(
                    {"customer": customer_id}
                    if customer_id
                    else {"customer_email": customer_email}
                    if customer_email
                    else {}
                ),
            }
            if mode == "subscription":
                params["subscription_data"] = {"metadata": metadata}
            else:
                # A one-time payment has no subscription to carry metadata, so it is attached to
                # the payment intent, which is what a refund event later refers to.
                params["payment_intent_data"] = {"metadata": metadata}

            checkout = await stripe.checkout.Session.create_async(**params)
            if not checkout.url:
                raise PaymentError("Stripe returned a checkout session with no URL")
            return CheckoutLink(session_id=checkout.id, url=checkout.url)
        except PaymentError:
            raise
        except stripe.StripeError as error:
            # ``user_message`` is Stripe's own customer-safe text; the raw error can name internal
            # parameters and is logged rather than returned.
            logging.error(f"Error in StripeProvider.create_checkout_link: {error}")
            raise PaymentError(error.user_message or "Checkout could not be started") from error
        except Exception as error:
            logging.error(f"Error in StripeProvider.create_checkout_link: {error}")
            raise PaymentError("Checkout could not be started") from error

    async def create_portal_link(self, *, customer_id: str, return_url: str) -> str:
        """
        Create a Stripe Customer Portal session.

        The portal is where cancellation, payment-method updates and invoice history live. Using
        Stripe's hosted portal rather than building those flows means this application never
        handles a card number and never has to implement proration.

        Args:
            customer_id: Stripe customer to open the portal for.
            return_url: Where the portal returns the user.

        Returns:
            str: Hosted portal URL.

        Raises:
            PaymentError: If Stripe rejected the request.
            PaymentConfigurationError: Stripe is not configured.
        """
        try:
            logging.info("Executing StripeProvider.create_portal_link")
            portal = await stripe.billing_portal.Session.create_async(
                api_key=self._require_api_key(), customer=customer_id, return_url=return_url
            )
            return portal.url
        except stripe.StripeError as error:
            logging.error(f"Error in StripeProvider.create_portal_link: {error}")
            raise PaymentError(error.user_message or "Billing portal is unavailable") from error
        except PaymentConfigurationError:
            raise
        except Exception as error:
            logging.error(f"Error in StripeProvider.create_portal_link: {error}")
            raise PaymentError("Billing portal is unavailable") from error

    def verify_event(self, *, payload: bytes, signature: str | None) -> ProviderEvent:
        """
        Verify a Stripe webhook signature and parse the event.

        ``construct_event`` checks an HMAC over the exact request bytes and rejects a timestamp
        outside its tolerance window, so a captured payload cannot be replayed indefinitely. This
        is the only thing separating a genuine payment from a POST that claims one, which is why
        an unconfigured signing secret refuses every request rather than falling back to trust.

        Args:
            payload: Exact request body as received.
            signature: Value of the ``Stripe-Signature`` header.

        Returns:
            ProviderEvent: The verified event.

        Raises:
            SignatureVerificationFailed: Missing, malformed or incorrect signature.
            PaymentConfigurationError: No signing secret is configured.
        """
        secret = settings.STRIPE_WEBHOOK_SECRET
        if not secret:
            raise PaymentConfigurationError("Stripe webhook signing secret is not configured")
        if not signature:
            raise SignatureVerificationFailed("Missing signature header")

        try:
            event = stripe.Webhook.construct_event(payload, signature, secret)
        except stripe.SignatureVerificationError as error:
            # Logged as a warning, not an error: an unsigned POST to a public webhook URL is
            # background noise on the internet, and treating it as a system fault would bury real
            # failures under it.
            logging.warning("Rejected a webhook payload with an invalid signature")
            raise SignatureVerificationFailed("Invalid signature") from error
        except ValueError as error:
            logging.warning("Rejected a webhook payload that was not valid JSON")
            raise SignatureVerificationFailed("Malformed payload") from error

        # `construct_event` returns a Stripe object, not a dict — it has no `.get`, and reading a
        # missing key raises rather than returning None. Converting once at the boundary is what
        # lets everything above treat the payload as ordinary untrusted data.
        parsed = event.to_dict()
        data = parsed.get("data") or {}
        return ProviderEvent(
            event_id=str(parsed.get("id") or ""),
            event_type=str(parsed.get("type") or ""),
            created_at=_timestamp(parsed.get("created")),
            payload=dict(data.get("object") or {}),
        )

    async def fetch_subscription(self, *, subscription_id: str) -> ProviderSubscription:
        """
        Read a subscription's current state from Stripe.

        Args:
            subscription_id: Stripe subscription identifier.

        Returns:
            ProviderSubscription: Normalised subscription state.

        Raises:
            PaymentError: If Stripe rejected the request.
            PaymentConfigurationError: Stripe is not configured.
        """
        try:
            logging.info("Executing StripeProvider.fetch_subscription")
            subscription = await stripe.Subscription.retrieve_async(
                subscription_id, api_key=self._require_api_key()
            )
            # Stripe objects are dict-like but not dicts; `to_dict` gives the plain mapping
            # the normaliser reads, and keeps the boundary honest about what crosses it.
            return self.to_subscription(subscription.to_dict())
        except stripe.StripeError as error:
            logging.error(f"Error in StripeProvider.fetch_subscription: {error}")
            raise PaymentError("Subscription could not be read") from error
        except PaymentConfigurationError:
            raise
        except Exception as error:
            logging.error(f"Error in StripeProvider.fetch_subscription: {error}")
            raise PaymentError("Subscription could not be read") from error

    @staticmethod
    def to_subscription(payload: dict[str, Any]) -> ProviderSubscription:
        """
        Normalise a Stripe subscription object into this application's shape.

        Shared by the webhook path and the reconciliation path so both interpret Stripe's fields
        identically — including the period dates, which Stripe moved from the subscription onto
        its items and still returns at the top level for older API versions. Reading both means
        the mirror is correct whichever shape arrives.

        Args:
            payload: A Stripe subscription object.

        Returns:
            ProviderSubscription: Normalised subscription state.
        """
        items = payload.get("items")
        first_item: dict[str, Any] = {}
        if isinstance(items, dict):
            data = items.get("data")
            if isinstance(data, list) and data and isinstance(data[0], dict):
                first_item = data[0]

        price = first_item.get("price")
        price_id = _string(price)

        period_start = _timestamp(payload.get("current_period_start")) or _timestamp(
            first_item.get("current_period_start")
        )
        period_end = _timestamp(payload.get("current_period_end")) or _timestamp(
            first_item.get("current_period_end")
        )

        raw_status = payload.get("status")
        status = _STATUS_MAP.get(
            raw_status if isinstance(raw_status, str) else "", SubscriptionStatus.INCOMPLETE
        )
        if not isinstance(raw_status, str) or raw_status not in _STATUS_MAP:
            logging.warning(f"Unrecognised Stripe subscription status {raw_status!r}")

        metadata = payload.get("metadata")
        return ProviderSubscription(
            provider_subscription_id=str(payload.get("id") or ""),
            provider_customer_id=_string(payload.get("customer")),
            status=status,
            price_id=price_id,
            current_period_start=period_start,
            current_period_end=period_end,
            cancel_at_period_end=bool(payload.get("cancel_at_period_end")),
            metadata={str(k): str(v) for k, v in metadata.items()}
            if isinstance(metadata, dict)
            else {},
        )
