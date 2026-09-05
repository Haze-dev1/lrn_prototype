"""Email preferences, one-click unsubscribe, and the public analytics endpoint.

Two of these three routes are unauthenticated, and both are deliberately narrow.

Unsubscribe has to work without a session — a student who wants the mail to stop must not have to
remember a password to say so, because the alternative control they have is the spam button. It
is authorised by a signed token instead, and the token can only ever turn a preference *off*.

The analytics endpoint accepts a fixed handful of events that genuinely only happen in a browser.
Everything else in the funnel is recorded server-side, where the event is a consequence of work
the API actually did.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status

from commons.auth import client_identifier, get_current_user
from commons.rate_limit import check_rate_limit
from core import logger
from core.apis.schemas.requests.email_request import (
    EmailPreferencesRequest,
    PublicEventRequest,
    UnsubscribeRequest,
)
from core.apis.schemas.responses.email_response import (
    EmailPreferencesResponse,
    UnsubscribeResponse,
)
from core.controllers.email_controller import EmailController
from core.models.user_model import User
from core.services.analytics.service import track

email_router = APIRouter()
logging = logger(__name__)

# Generous, because this only guards a counter. It exists to stop a script filling the analytics
# store, not to police ordinary traffic — and students share campus addresses, so a tight per-IP
# limit here would silently drop a whole university's landing views.
PUBLIC_EVENT_RATE_LIMIT = 120
PUBLIC_EVENT_WINDOW_SECONDS = 60


@email_router.get("/v1/account/email-preferences", response_model=EmailPreferencesResponse)
async def get_email_preferences(
    user: User = Depends(get_current_user),
) -> EmailPreferencesResponse:
    """
    Read the caller's own email preferences.

    Returns:
        EmailPreferencesResponse: Current preferences.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling GET /v1/account/email-preferences endpoint")
        return EmailPreferencesResponse(**await EmailController().get_preferences(user=user))
    except HTTPException as httperror:
        logging.error(f"Error in GET /v1/account/email-preferences endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in GET /v1/account/email-preferences endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@email_router.put("/v1/account/email-preferences", response_model=EmailPreferencesResponse)
async def set_email_preferences(
    request: EmailPreferencesRequest, user: User = Depends(get_current_user)
) -> EmailPreferencesResponse:
    """
    Update the caller's own email preferences.

    Takes no user ID, like every account route: it operates on the authenticated caller, which
    removes the "change the ID in the body to unsubscribe someone else" class of bug entirely.

    Args:
        request: The new preferences.
        user: The authenticated caller.

    Returns:
        EmailPreferencesResponse: The stored preferences.

    Raises:
        HTTPException 401: Not authenticated.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling PUT /v1/account/email-preferences endpoint")
        return EmailPreferencesResponse(
            **await EmailController().set_preferences(
                user=user,
                study_reminder_emails=request.study_reminder_emails,
                marketing_emails_opt_in=request.marketing_emails_opt_in,
            )
        )
    except HTTPException as httperror:
        logging.error(f"Error in PUT /v1/account/email-preferences endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in PUT /v1/account/email-preferences endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@email_router.post("/v1/emails/unsubscribe", response_model=UnsubscribeResponse)
async def unsubscribe(request: UnsubscribeRequest) -> UnsubscribeResponse:
    """
    Turn study reminders off from an emailed link, with no session.

    A POST rather than a GET, even though the link in the email is a URL. Mail scanners and link
    previewers fetch every URL in a message, and an unsubscribe that happened on GET would
    unsubscribe people who never clicked anything. The emailed link opens a page; the page makes
    this request.

    Always answers the same way, whether the token matched a live account or not. Distinguishing
    them would turn a public endpoint into a way to test whether an address is registered.

    Args:
        request: The signed token from the email.

    Returns:
        UnsubscribeResponse: A confirmation that reveals nothing about the account.

    Raises:
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/emails/unsubscribe endpoint")
        await EmailController().unsubscribe(token=request.token)
        return UnsubscribeResponse(
            message="Study reminders are off. You will still receive your results and receipts."
        )
    except HTTPException as httperror:
        logging.error(f"Error in POST /v1/emails/unsubscribe endpoint: {httperror.detail}")
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/emails/unsubscribe endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error


@email_router.post("/v1/analytics/events", status_code=status.HTTP_202_ACCEPTED)
async def record_public_event(request: PublicEventRequest, http_request: Request) -> dict[str, str]:
    """
    Record one of the few events that only a browser can observe.

    Accepts an event name and nothing else. There is no properties field, because a property bag
    from an untrusted client is a free-text channel into the analytics store, and the whole point
    of the allowlist above it is that free text never gets there.

    Answers 202 for an event it declines to record. A browser can do nothing useful with the
    refusal, and returning 400 would only tell a prober which names are recognised.

    Args:
        request: The event name.
        http_request: The incoming request, for rate limiting.

    Returns:
        dict[str, str]: Acknowledgement.

    Raises:
        HTTPException 429: Too many events from one address.
        HTTPException 500: Internal server error.
    """
    try:
        logging.info("Calling POST /v1/analytics/events endpoint")
        allowed = await check_rate_limit(
            bucket="analytics",
            identifier=client_identifier(http_request),
            limit=PUBLIC_EVENT_RATE_LIMIT,
            window_seconds=PUBLIC_EVENT_WINDOW_SECONDS,
        )
        if not allowed.allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests"
            )

        if not PublicEventRequest.is_permitted(request.event):
            logging.warning(f"Declined to record non-public analytics event {request.event!r}")
            return {"status": "ignored"}

        track(event=request.event, properties={"surface": "web"})
        return {"status": "accepted"}
    except HTTPException as httperror:
        raise httperror
    except Exception as error:
        logging.error(f"Error in POST /v1/analytics/events endpoint: {error}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error"
        ) from error
