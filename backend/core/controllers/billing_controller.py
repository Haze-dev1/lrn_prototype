"""Billing orchestration: what is for sale, what the caller has, and how to pay for more.

The controller owns one rule that the rest of the file exists to serve: **this endpoint cannot
grant access.** Starting a checkout creates a link and nothing else. No entitlement is written, no
subscription is mirrored, and nothing about the caller's access changes until a signed event
arrives from the provider saying money moved. A student who opens the checkout URL and closes the
tab is exactly as unentitled as before, and so is one who forges a request to this endpoint.
"""

from typing import Any

from fastapi import HTTPException, status

from core import logger
from core.config.settings import settings
from core.constants.enums import Plan
from core.cruds.billing_crud import CRUDSubscription
from core.models.user_model import User
from core.services.analytics.events import AnalyticsEvent
from core.services.analytics.service import track
from core.services.billing.entitlement_service import AccessState, EntitlementService
from core.services.billing.plans import PLANS, get_plan
from core.services.billing.provider import (
    PaymentConfigurationError,
    PaymentError,
    get_payment_provider,
)

logging = logger(__name__)


class BillingController:
    """Serves the plan catalogue and entitlement state, and starts provider-hosted flows."""

    def __init__(self) -> None:
        """Initialise the controller with the services and CRUD layers it coordinates."""
        self.EntitlementService = EntitlementService()
        self.CRUDSubscription = CRUDSubscription()

    @staticmethod
    def serialise_access(access: AccessState) -> dict[str, Any]:
        """
        Flatten an access state into the response payload.

        Every capability is sent as an already-decided boolean rather than as the inputs to a
        decision. The interface must not be able to compute access differently from the endpoint
        that enforces it — that is how a paywall ends up shown to someone who paid, or hidden from
        someone who did not.

        Args:
            access: The resolved access state.

        Returns:
            dict[str, Any]: Payload matching ``EntitlementResponse``.
        """
        usage = access.usage
        return {
            "plan": access.plan,
            "is_paid": access.is_paid,
            "active_until": access.active_until,
            "expired_at": access.expired_at,
            "cancel_at_period_end": access.cancel_at_period_end,
            "can_manage_billing": access.has_billing_account,
            "can_start_practice": access.can_start_practice,
            "can_grade_answer": access.can_grade_answer,
            "can_start_new_diagnostic": access.can_start_new_diagnostic,
            "usage": {
                "diagnostics_taken": usage.diagnostics_taken,
                "practice_sessions_used": usage.practice_sessions_used,
                "practice_sessions_limit": usage.practice_sessions_limit,
                "practice_sessions_remaining": usage.practice_sessions_remaining,
                "graded_last_24h": usage.graded_today,
                "daily_grade_limit": usage.daily_grade_limit,
                "grades_remaining_today": usage.grades_remaining_today,
            },
        }

    async def entitlements(self, *, user: User) -> dict[str, Any]:
        """
        Report the caller's current access and free-tier usage.

        Args:
            user: The authenticated caller.

        Returns:
            dict[str, Any]: Payload matching ``EntitlementResponse``.

        Raises:
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing BillingController.entitlements")
            access = await self.EntitlementService.access_for(user=user)
            return self.serialise_access(access)
        except Exception as error:
            logging.error(f"Error in BillingController.entitlements: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def plans(self, *, user: User | None) -> dict[str, Any]:
        """
        Return the plan catalogue, with the caller's position in it when signed in.

        Public, because pricing is a page anyone can read. A signed-in caller additionally gets
        their entitlement, so the page can say "you are on Pro" instead of trying to sell them
        what they already have.

        Args:
            user: The caller, or None for an anonymous visitor.

        Returns:
            dict[str, Any]: Payload matching ``PlansResponse``.

        Raises:
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing BillingController.plans")
            catalogue = [
                {
                    "plan": definition.plan,
                    "name": definition.name,
                    "tagline": definition.tagline,
                    "features": list(definition.features),
                    # The free plan is always available; a paid one needs a configured price.
                    "purchasable": definition.plan is Plan.FREE or definition.purchasable,
                    "one_time": definition.checkout_mode == "payment",
                    "duration_days": definition.duration_days,
                }
                for definition in PLANS
            ]
            entitlement = None
            if user is not None:
                entitlement = self.serialise_access(
                    await self.EntitlementService.access_for(user=user)
                )
            return {
                "plans": catalogue,
                "entitlement": entitlement,
                "billing_enabled": settings.billing_enabled,
            }
        except Exception as error:
            logging.error(f"Error in BillingController.plans: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def start_checkout(self, *, user: User, plan: str) -> str:
        """
        Create a hosted checkout link for one plan.

        Refuses when the caller already holds paid access. Letting someone buy a second
        overlapping entitlement takes their money for nothing and produces a support conversation
        that ends in a refund; the Customer Portal is where an existing customer changes plan.

        Args:
            user: The authenticated caller.
            plan: Plan identifier to purchase.

        Returns:
            str: The provider-hosted checkout URL.

        Raises:
            HTTPException 400: The plan is unknown or not purchasable.
            HTTPException 409: The caller already has paid access.
            HTTPException 502: The provider rejected the request.
            HTTPException 503: Billing is not configured in this deployment.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing BillingController.start_checkout")
            if not settings.billing_enabled:
                logging.warning("Checkout requested while billing is not configured")
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Payments are not available right now.",
                )

            definition = get_plan(plan)
            if definition is None or definition.checkout_mode is None:
                logging.warning(f"Checkout requested for unpurchasable plan {plan!r}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST, detail="That plan cannot be purchased."
                )
            price_id = definition.price_id
            if not price_id:
                logging.warning(f"Plan {plan!r} has no configured price")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="That plan is not available right now.",
                )

            access = await self.EntitlementService.access_for(user=user)
            if access.is_paid:
                logging.warning(f"User {user.id} started checkout while already entitled")
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="You already have access. Manage your plan from your account.",
                )

            customer_id = await self.CRUDSubscription.get_customer_id_for_user(user_id=user.id)
            base = settings.PUBLIC_WEB_URL.rstrip("/")
            link = await get_payment_provider().create_checkout_link(
                price_id=price_id,
                mode=definition.checkout_mode,
                client_reference_id=str(user.id),
                customer_email=user.email,
                customer_id=customer_id,
                # The success page confirms access rather than granting it: it polls this API
                # until the webhook has landed, so a delayed event shows as "confirming" and
                # never as access the browser awarded itself.
                success_url=f"{base}/billing/success",
                cancel_url=f"{base}/pricing?checkout=cancelled",
                metadata={"user_id": str(user.id), "plan": str(definition.plan)},
            )
            logging.info(f"Created a {definition.plan} checkout session for user {user.id}")
            # Started, not completed. The pair is what makes checkout abandonment readable, and
            # the completion can only ever come from a verified payment event.
            track(
                event=AnalyticsEvent.CHECKOUT_STARTED,
                user_id=user.id,
                properties={"plan": definition.plan},
            )
            return link.url
        except HTTPException:
            raise
        except PaymentConfigurationError as error:
            logging.error(f"Error in BillingController.start_checkout: {error}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Payments are not available right now.",
            ) from error
        except PaymentError as error:
            # 502, not 500: the failure is downstream, and saying so keeps a provider outage from
            # being investigated as an application bug.
            logging.error(f"Error in BillingController.start_checkout: {error}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Checkout could not be started. Please try again.",
            ) from error
        except Exception as error:
            logging.error(f"Error in BillingController.start_checkout: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error

    async def open_portal(self, *, user: User) -> str:
        """
        Create a Customer Portal link for managing or cancelling a plan.

        The portal is the provider's, not this application's. Cancellation, payment methods and
        invoices all live there, which means no card detail ever reaches this system and a
        cancellation is recorded by the provider that has to honour it.

        Args:
            user: The authenticated caller.

        Returns:
            str: The provider-hosted portal URL.

        Raises:
            HTTPException 404: The caller has never had a billing account.
            HTTPException 502: The provider rejected the request.
            HTTPException 503: Billing is not configured in this deployment.
            HTTPException 500: Unexpected failure.
        """
        try:
            logging.info("Executing BillingController.open_portal")
            customer_id = await self.CRUDSubscription.get_customer_id_for_user(user_id=user.id)
            if not customer_id:
                logging.warning(f"User {user.id} opened the portal with no billing account")
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="You do not have a billing account yet.",
                )
            base = settings.PUBLIC_WEB_URL.rstrip("/")
            return await get_payment_provider().create_portal_link(
                customer_id=customer_id, return_url=f"{base}/account"
            )
        except HTTPException:
            raise
        except PaymentConfigurationError as error:
            logging.error(f"Error in BillingController.open_portal: {error}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Billing management is not available right now.",
            ) from error
        except PaymentError as error:
            logging.error(f"Error in BillingController.open_portal: {error}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Billing management is unavailable. Please try again.",
            ) from error
        except Exception as error:
            logging.error(f"Error in BillingController.open_portal: {error}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
            ) from error
