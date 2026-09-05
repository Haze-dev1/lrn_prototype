"""Email rendering.

Three messages, written as functions rather than loaded from a template engine. There is no
template language here on purpose: three messages do not justify a rendering dependency, a
template directory to ship into the image, and a second place where escaping can go wrong.

Two rules run through all of them.

**Every value that reaches the HTML is escaped.** A school name, a category name and a subject
line all come from data, and one of them is student-supplied. ``html.escape`` is applied at the
point of interpolation, not trusted to have happened earlier.

**No rubric content, ever.** These messages carry scores, category names and counts. They never
carry an ideal answer, an expected concept, a common mistake, or the student's own answer text —
email is forwarded, archived and indexed by systems this application does not control, and a
rubric that leaks by email leaks permanently.
"""

from dataclasses import dataclass
from html import escape

from core.config.settings import settings

# Inlined rather than linked: every mail client blocks or strips an external stylesheet, and a
# message that arrives unstyled in half the world's inboxes is not styled at all. Kept close to
# the product's own palette without depending on it — a design token change must not silently
# alter mail that has already been sent.
_INK = "#0f1419"
_MUTED = "#5c6773"
_ACCENT = "#0f6c8c"
_RULE = "#e3e8ef"

_FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


@dataclass(frozen=True)
class RenderedEmail:
    """A subject line with both bodies."""

    subject: str
    html: str
    text: str


def _shell(*, heading: str, body: str, footer: str) -> str:
    """
    Wrap rendered content in the message frame.

    A table-based frame with inline styles, because that is what mail clients actually render;
    a flex layout would collapse in Outlook and be centred nowhere.

    Args:
        heading: Already-escaped headline.
        body: Already-escaped and marked-up body content.
        footer: Already-escaped and marked-up footer content.

    Returns:
        str: Complete HTML document.
    """
    return f"""<!doctype html>
<html><body style="margin:0;padding:0;background:#f6f8fa;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"
       style="background:#f6f8fa;padding:32px 16px;">
  <tr><td align="center">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
           style="max-width:560px;background:#ffffff;border:1px solid {_RULE};border-radius:10px;">
      <tr><td style="padding:32px 32px 8px 32px;font-family:{_FONT};">
        <div style="font-size:11px;letter-spacing:0.1em;text-transform:uppercase;color:{_MUTED};">
          LRN
        </div>
        <h1 style="margin:14px 0 0 0;font-size:22px;line-height:1.3;color:{_INK};font-weight:600;">
          {heading}
        </h1>
      </td></tr>
      <tr><td style="padding:16px 32px 32px 32px;font-family:{_FONT};font-size:15px;
                     line-height:1.6;color:{_INK};">
        {body}
      </td></tr>
      <tr><td style="padding:20px 32px;border-top:1px solid {_RULE};font-family:{_FONT};
                     font-size:12px;line-height:1.6;color:{_MUTED};">
        {footer}
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>"""


def _button(*, href: str, label: str) -> str:
    """
    Render a call-to-action as an anchor styled to look like a button.

    An anchor rather than a button element: a real button does nothing in an email, and clients
    strip the element entirely.

    Args:
        href: Destination URL.
        label: Already-escaped label.

    Returns:
        str: Markup for the action.
    """
    return (
        f'<a href="{escape(href, quote=True)}" '
        f'style="display:inline-block;background:{_INK};color:#ffffff;text-decoration:none;'
        f'padding:11px 20px;border-radius:6px;font-size:14px;font-weight:600;">{label}</a>'
    )


def _web(path: str) -> str:
    """
    Build an absolute link into the application.

    Args:
        path: Path beginning with a slash.

    Returns:
        str: Absolute URL.
    """
    return f"{settings.PUBLIC_WEB_URL.rstrip('/')}{path}"


def _transactional_footer() -> str:
    """
    Footer for a message the student's own action caused.

    Says why it arrived and offers no unsubscribe, because there is nothing to unsubscribe from:
    a results email is a consequence of finishing a diagnostic, not a mailing list.

    Returns:
        str: Footer markup.
    """
    return (
        "You are receiving this because of activity on your LRN account. "
        f'<a href="{escape(_web("/account"), quote=True)}" style="color:{_ACCENT};">'
        "Manage your account</a>."
    )


def _lifecycle_footer(unsubscribe: str) -> str:
    """
    Footer for a message the product initiated.

    The unsubscribe is a plain visible link, not a hidden one and not a preferences page that
    requires signing in. A student who wants these to stop has to be able to stop them in one
    click, or they will use the only other control they have, which is the spam button.

    Args:
        unsubscribe: Absolute unsubscribe URL.

    Returns:
        str: Footer markup.
    """
    return (
        "You are receiving this because study reminders are on for your LRN account. "
        f'<a href="{escape(unsubscribe, quote=True)}" style="color:{_ACCENT};">'
        "Turn these off</a> — one click, no sign-in needed."
    )


def render_diagnostic_results(
    *,
    overall: int | None,
    weakest_name: str | None,
    weakest_score: int | None,
    strongest_name: str | None,
    measured_categories: int,
    session_id: str,
) -> RenderedEmail:
    """
    Render the diagnostic results email.

    Reports the shape of the result and sends the student back to the product for the detail. The
    email deliberately does not reproduce the results page: a score in an inbox is a number, and
    the thing that makes it useful — the per-category breakdown and the recommended next step —
    only works where the student can act on it.

    Args:
        overall: Overall mastery, or None when nothing could be measured.
        weakest_name: Weakest measured category.
        weakest_score: That category's score.
        strongest_name: Strongest measured category.
        measured_categories: How many categories produced a score.
        session_id: The diagnostic, for the results link.

    Returns:
        RenderedEmail: Subject and both bodies.
    """
    link = _web(f"/diagnostic/{session_id}/results")

    if overall is None or weakest_name is None:
        # Grading failed for enough answers that no honest number exists. Saying so is the only
        # option: inventing a score from partial evidence would make the one number the student
        # actually reads a wrong one.
        subject = "Your LRN diagnostic could not be fully graded"
        lead = (
            "We could not finish grading enough of your diagnostic to report a readiness score. "
            "Your answers are saved and nothing is lost — open your results to see where it "
            "stands."
        )
        html_body = f"<p style='margin:0 0 20px 0;'>{escape(lead)}</p>{_button(href=link, label='Open your results')}"
        text_body = f"{lead}\n\n{link}"
        return RenderedEmail(
            subject=subject,
            html=_shell(
                heading=escape("Your diagnostic needs another look"),
                body=html_body,
                footer=_transactional_footer(),
            ),
            text=f"Your diagnostic needs another look\n\n{text_body}\n",
        )

    subject = f"Your LRN diagnostic: {overall}/100 overall"
    weakest_line = (
        f"{weakest_name} is your weakest area at {weakest_score}."
        if weakest_score is not None
        else f"{weakest_name} is your weakest area."
    )
    strongest_line = f"{strongest_name} is your strongest." if strongest_name else ""

    html_body = (
        f"<p style='margin:0 0 6px 0;color:{_MUTED};font-size:13px;'>"
        f"{escape(f'Across {measured_categories} measured categories')}</p>"
        f"<p style='margin:0 0 20px 0;font-size:40px;line-height:1;font-weight:600;'>"
        f"{overall}<span style='font-size:18px;color:{_MUTED};font-weight:400;'>/100</span></p>"
        f"<p style='margin:0 0 8px 0;'>{escape(weakest_line)}</p>"
        + (f"<p style='margin:0 0 20px 0;'>{escape(strongest_line)}</p>" if strongest_line else "")
        + _button(href=link, label="See the full breakdown")
        + "<p style='margin:20px 0 0 0;font-size:13px;color:"
        + _MUTED
        + ";'>Your results page shows every category, the concepts you missed, and the one "
        "practice set that will move your readiness furthest.</p>"
    )

    text_body = "\n".join(
        part
        for part in [
            f"Across {measured_categories} measured categories, you scored {overall}/100 overall.",
            "",
            weakest_line,
            strongest_line,
            "",
            "See the full breakdown, including the concepts you missed and what to practise next:",
            link,
        ]
        if part is not None
    )

    return RenderedEmail(
        subject=subject,
        html=_shell(
            heading=escape("Where you stand today"),
            body=html_body,
            footer=_transactional_footer(),
        ),
        text=f"Where you stand today\n\n{text_body}\n",
    )


def render_payment_receipt(*, plan_name: str, access_until: str | None) -> RenderedEmail:
    """
    Render the confirmation sent when paid access begins.

    Confirms access, not the charge. The payment provider issues the tax receipt and holds the
    card detail; duplicating that here would mean rendering amounts this application would have to
    keep in step with the provider's own record, and getting it wrong on a receipt is worse than
    not sending one.

    Args:
        plan_name: Human name of the plan.
        access_until: Formatted end date, or None for a subscription with no end.

    Returns:
        RenderedEmail: Subject and both bodies.
    """
    window = (
        f"Your access runs until {access_until}."
        if access_until
        else "Your subscription renews automatically, and you can cancel any time from your "
        "account."
    )
    lead = (
        f"{plan_name} is active. Adaptive practice, spaced repetition of everything you have "
        "missed, and your full review history are open."
    )
    link = _web("/practice")

    html_body = (
        f"<p style='margin:0 0 12px 0;'>{escape(lead)}</p>"
        f"<p style='margin:0 0 20px 0;'>{escape(window)}</p>"
        + _button(href=link, label="Start practising")
        + f"<p style='margin:20px 0 0 0;font-size:13px;color:{_MUTED};'>"
        + escape(
            "Invoices and payment methods live in your billing portal, reachable from your "
            "account page."
        )
        + "</p>"
    )
    text_body = f"{lead}\n\n{window}\n\nStart practising: {link}\n"

    return RenderedEmail(
        subject=f"{plan_name} is active on LRN",
        html=_shell(
            heading=escape("You have full access"),
            body=html_body,
            footer=_transactional_footer(),
        ),
        text=f"You have full access\n\n{text_body}",
    )


def render_weak_area_nudge(
    *,
    weakest_name: str,
    weakest_score: int,
    review_due_count: int,
    unsubscribe: str,
) -> RenderedEmail:
    """
    Render the weekly weak-area nudge.

    It says one specific thing — the weakest category, its score, and how many previously missed
    questions are due for review — and offers one action. A weekly email that reports general
    progress is a newsletter, and a newsletter about your own study habits is the kind of mail
    people stop opening and then start reporting.

    Args:
        weakest_name: The student's weakest measured category.
        weakest_score: That category's mastery score.
        review_due_count: Previously missed questions whose interval has elapsed.
        unsubscribe: Absolute unsubscribe URL.

    Returns:
        RenderedEmail: Subject and both bodies.
    """
    link = _web("/practice")
    due_line = (
        f"{review_due_count} question{'' if review_due_count == 1 else 's'} you previously missed "
        f"{'is' if review_due_count == 1 else 'are'} due for review."
        if review_due_count
        else "A focused set there will move your readiness further than anything else this week."
    )

    html_body = (
        f"<p style='margin:0 0 12px 0;'>"
        f"{escape(f'{weakest_name} is sitting at {weakest_score}.')} {escape(due_line)}</p>"
        f"<p style='margin:0 0 20px 0;'>"
        + escape("Ten questions is about thirty minutes.")
        + "</p>"
        + _button(href=link, label=f"Practise {weakest_name}")
    )
    text_body = (
        f"{weakest_name} is sitting at {weakest_score}. {due_line}\n\n"
        f"Ten questions is about thirty minutes.\n\n{link}\n"
    )

    return RenderedEmail(
        subject=f"{weakest_name} is your weakest area this week",
        html=_shell(
            heading=escape("One thing to work on"),
            body=html_body,
            footer=_lifecycle_footer(unsubscribe),
        ),
        text=f"One thing to work on\n\n{text_body}",
    )
