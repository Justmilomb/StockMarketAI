"""Email template registry + Jinja2 renderer.

Admin-facing email library. Each template lives as a pair of Jinja2
files in ``server/templates/emails/`` — one ``.html.j2`` and one
``.txt.j2`` — and is described here with a human label and the list of
required context variables for the admin UI to render an input form.

Usage:

    from server.email_templates import render, TEMPLATES
    html, text = render("welcome_new_license", {...}, recipient="a@b.c")

Render failures (missing variables, malformed template) raise Jinja2
exceptions — the admin UI converts those into a validation error for
the operator. Emails are never sent with placeholder values.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates", "emails")

_env_html: Environment = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=select_autoescape(["html", "htm", "j2"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_env_text: Environment = Environment(
    loader=FileSystemLoader(_TEMPLATE_DIR),
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


@dataclass(frozen=True)
class TemplateSpec:
    id: str
    label: str
    subject: str
    required_vars: List[str]
    # Vars that must be typed in by a human — the system cannot auto-fill
    # them. When non-empty, event triggers route through _queue_admin_fill
    # instead of sending directly.
    admin_vars: List[str] = field(default_factory=list)


#: Every template the admin UI knows about. Add a new row + two .j2 files
#: and the admin Email tab picks it up automatically on reload.
TEMPLATES: List[TemplateSpec] = [
    TemplateSpec(
        id="welcome_new_license",
        label="Welcome (account created)",
        subject="Your blank account is ready",
        required_vars=["name"],
    ),
    TemplateSpec(
        id="verify_email",
        label="Verify email (signup)",
        subject="Verify your blank email",
        required_vars=["name", "verify_url"],
    ),
    TemplateSpec(
        id="waitlist_joined",
        label="Waitlist — thanks for signing up",
        subject="You're on the blank waitlist",
        required_vars=["name", "launch_date"],
    ),
    TemplateSpec(
        id="release_announcement",
        label="Release announcement",
        subject="blank {{ version }} is out",
        required_vars=["version", "headline", "intro", "highlights"],
    ),
    TemplateSpec(
        id="maintenance_notice",
        label="Scheduled maintenance notice",
        subject="blank — scheduled maintenance",
        required_vars=["start_time", "end_time", "reason"],
    ),
    TemplateSpec(
        id="launch_day_announcement",
        label="Launch day blast",
        subject="blank is live",
        required_vars=["name"],
    ),
    TemplateSpec(
        id="waitlist_repeat",
        label="Waitlist — already signed up",
        subject="You're already on the blank waitlist",
        required_vars=["name", "launch_date"],
    ),
    TemplateSpec(
        id="incident_notice",
        label="Incident notice (unscheduled)",
        subject="blank — incident notice",
        required_vars=["summary", "status_url"],
    ),
    TemplateSpec(
        id="license_expiring",
        label="Licence expiring (7-day reminder)",
        subject="Your blank licence expires soon",
        required_vars=["name", "license_key", "expires_at", "renew_url"],
    ),
    TemplateSpec(
        id="license_renewed",
        label="Licence renewed — thanks",
        subject="Your blank licence is renewed",
        required_vars=["name", "license_key", "next_renewal"],
    ),
    TemplateSpec(
        id="license_revoked",
        label="Licence revoked (admin action)",
        subject="Your blank licence has been revoked",
        required_vars=["name", "reason", "contact_url"],
        admin_vars=["reason"],
    ),
    TemplateSpec(
        id="first_time_tips",
        label="Day-one onboarding tips",
        subject="Getting the most out of blank",
        required_vars=["name", "tips"],
    ),
    TemplateSpec(
        id="feature_spotlight",
        label="Feature spotlight — what's new",
        subject="What's new in blank {{ version }}",
        required_vars=["version", "headline", "intro", "features"],
    ),
    TemplateSpec(
        id="holiday_check_in",
        label="Markets-closed weekly summary",
        subject="blank — the week in review",
        required_vars=["name", "period_start", "period_end", "highlights"],
    ),
    TemplateSpec(
        id="feedback_request",
        label="Feedback request (14 days in)",
        subject="How's blank treating you?",
        required_vars=["name", "form_url"],
    ),
    TemplateSpec(
        id="account_action_required",
        label="Generic — action required",
        subject="blank — action required",
        required_vars=["name", "headline", "body", "cta_label", "cta_url"],
    ),
]


def list_templates() -> List[Dict[str, Any]]:
    """Return a JSON-safe list of template specs for the admin UI."""
    return [
        {
            "id": t.id,
            "label": t.label,
            "subject": t.subject,
            "required_vars": list(t.required_vars),
            "admin_vars": list(t.admin_vars),
        }
        for t in TEMPLATES
    ]


def _spec(template_id: str) -> TemplateSpec:
    for t in TEMPLATES:
        if t.id == template_id:
            return t
    raise KeyError(f"unknown email template: {template_id}")


def render(
    template_id: str,
    ctx: Dict[str, Any],
    *,
    recipient: str,
    unsubscribe_url: str = "",
) -> Tuple[str, str, str]:
    """Render a template to ``(subject, html, text)``.

    ``ctx`` must include every entry in ``required_vars`` for the spec.
    ``StrictUndefined`` makes missing variables raise instead of rendering
    the empty string — we want the admin to fix the input, not send
    half-filled email.
    """
    spec = _spec(template_id)
    full_ctx: Dict[str, Any] = {
        "recipient": recipient,
        "unsubscribe_url": unsubscribe_url,
        "subject": spec.subject,
        **ctx,
    }

    # Subject is a mini-template too so we can interpolate e.g. the version.
    subject = _env_text.from_string(spec.subject).render(**full_ctx)
    full_ctx["subject"] = subject

    html = _env_html.get_template(f"{template_id}.html.j2").render(**full_ctx)
    text = _env_text.get_template(f"{template_id}.txt.j2").render(**full_ctx)
    return subject, html, text
