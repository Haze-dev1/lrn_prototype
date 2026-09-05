"""Billing endpoints: the plan catalogue, entitlement state, hosted flows and the webhook.

Note what is absent. There is no endpoint that sets a plan, extends access, or marks a payment
complete. The only route here that changes what a user may do is the webhook, and it acts only on
a payload carrying a valid provider signature. Everything else reads state or hands back a link.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from commons.auth import get_current_user, get_optional_user
from core import logger
from core.apis.schemas.requests.billing_request import CheckoutRequest
from core.apis.schemas.responses.billing_response import (
    CheckoutResponse,
    EntitlementResponse,
    PlansResponse,
    PortalResponse,
)
from core.controllers.billing_controller import BillingController
from core.models.user_model import User
from core.services.billing.provider import (
    PaymentConfigurationError,
    SignatureVerificationFailed,
)
from core.services.billing.webhook_service import BillingWebhookService

billing_router = APIRouter()
logging = logger(__name__)


@billing_router.get("/v1/billing/plans", response_model=PlansResponse)
async def list_plans(user: User | None = Depends(get_optional_user)) -> PlansResponse:
    """
    Read the plan catalogue, with the caller's current access when signed in.

    Public: pricing is a page anyone can read, and requiring an account to see what something
    costs is a conversion problem, not a security one.

    Args:
        user: The caller, or None when anonymous.

    Returns:
        PlansResponse: Plans, the caller's entitlement, and whether payments are configured.

    Raises:
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/billing/plans endpoint")
        return PlansResponse(**await BillingController().plans(user=user))
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/billing/plans endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/billing/plans endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@billing_router.get("/v1/entitlements", response_model=EntitlementResponse)
async def get_entitlements(user: User = Depends(get_current_user)) -> EntitlementResponse:
    """
    Read the caller's own access and free-tier usage.

    Takes no user ID. Like every account endpoint it operates on the authenticated caller, which
    removes the "change the ID in the URL to read someone else's plan" class of bug entirely.

    Args:
        user: The authenticated caller.

    Returns:
        EntitlementResponse: Plan, capabilities and free-tier usage.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/entitlements endpoint")
        return EntitlementResponse(**await BillingController().entitlements(user=user))
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/entitlements endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/entitlements endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@billing_router.post("/v1/billing/checkout", response_model=CheckoutResponse)
async def start_checkout(
    request: CheckoutRequest, user: User = Depends(get_current_user)
) -> CheckoutResponse:
    """
    Start a hosted checkout for one plan and return where to send the browser.

    Returning a URL rather than redirecting keeps the caller in control of the navigation and
    lets the interface show its own pending state first. Nothing about the caller's access changes
    here; only a signed webhook can do that.

    Args:
        request: The plan to purchase.
        user: The authenticated caller.

    Returns:
        CheckoutResponse: The provider-hosted checkout URL.

    Raises:
        HTTPException 400: Unknown or unpurchasable plan.
        HTTPException 401: Not authenticated.
        HTTPException 409: The caller already has paid access.
        HTTPException 502: The payment provider rejected the request.
        HTTPException 503: Payments are not configured.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/billing/checkout endpoint")
        url = await BillingController().start_checkout(user=user, plan=request.plan)
        return CheckoutResponse(url=url)
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/billing/checkout endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/billing/checkout endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@billing_router.post("/v1/billing/portal", response_model=PortalResponse)
async def open_portal(user: User = Depends(get_current_user)) -> PortalResponse:
    """
    Open the provider's Customer Portal for the caller's billing account.

    Args:
        user: The authenticated caller.

    Returns:
        PortalResponse: The provider-hosted portal URL.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 404: The caller has no billing account.
        HTTPException 502: The payment provider rejected the request.
        HTTPException 503: Billing management is not configured.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/billing/portal endpoint")
        return PortalResponse(url=await BillingController().open_portal(user=user))
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/billing/portal endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/billing/portal endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@billing_router.post("/v1/webhooks/stripe", status_code=status.HTTP_200_OK)
async def stripe_webhook(request: Request) -> dict[str, str]:
    """
    Receive, verify and apply one Stripe event.

    Unauthenticated by necessity — Stripe has no session — and therefore authenticated by
    signature instead. The **raw request body** is read rather than a parsed model: the signature
    covers the exact bytes Stripe sent, and letting FastAPI parse and re-serialise the payload
    would change them and fail every verification.

    The status codes matter to the sender. A bad signature is 400, which stops Stripe retrying a
    payload that will never verify. A handler failure is 500, which makes Stripe retry with
    backoff — the delivery is the only copy of that event, and answering 200 to a delivery that
    changed nothing would discard a payment silently.

    Args:
        request: The raw incoming request.

    Returns:
        dict[str, str]: Acknowledgement describing what was done.

    Raises:
        HTTPException 400: Missing, malformed or invalid signature.
        HTTPException 500: The event was verified but could not be applied; retry expected.
        HTTPException 503: No signing secret is configured.
    """
    try:
        logging.info("Calling POST /v1/webhooks/stripe endpoint")
        payload = await request.body()
        result = await BillingWebhookService().handle(
            payload=payload, signature=request.headers.get("stripe-signature")
        )
        return {"status": str(result.get("status", "received"))}
    except SignatureVerificationFailed:
        # Deliberately not logged as an error: an unsigned POST to a public URL is background
        # noise, and treating it as a fault would bury real failures underneath it.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature"
        ) from None
    except PaymentConfigurationError as error:
        logging.error("Webhook received while no signing secret is configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhooks are not configured"
        ) from error
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/webhooks/stripe endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/webhooks/stripe endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error
