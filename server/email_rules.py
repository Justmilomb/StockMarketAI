"""Per-template trigger metadata for the email library.

Every row in :data:`server.email_templates.TEMPLATES` pairs with an
entry here describing **when** that template fires. Three kinds:

* ``"event"``     — fired inline from an existing endpoint (licence
                    created, waitlist signup, revoke, renew).
* ``"scheduled"`` — fired by :func:`server.app.admin_emails_tick`
                    based on a daily sweep of the DB.
* ``"manual"``    — announcements. Never auto-fires; the admin UI's
                    Send button is the only path.

Idempotency lives on the ``email_sent`` table (one row per
``(recipient, template_id, reason_key)``), not here. ``reason_key`` is
a short stable string computed by the caller so retries, re-deploys,
and duplicate ticks don't re-send the same mail.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class TriggerSpec:
    """Human-facing description of what makes a template fire."""
    kind: str           # "event" | "scheduled" | "manual"
    rule: str           # one-line description shown in admin UI


TRIGGERS: Dict[str, TriggerSpec] = {
    # ── event-driven ────────────────────────────────────────────────
    "welcome_new_license": TriggerSpec(
        kind="event",
        rule="sent when a new licence is issued (signup or admin create)",
    ),
    "waitlist_joined": TriggerSpec(
        kind="event",
        rule="sent on first waitlist signup for a given email",
    ),
    "waitlist_repeat": TriggerSpec(
        kind="event",
        rule="sent when a waitlist signup hits an email that already exists",
    ),
    "license_renewed": TriggerSpec(
        kind="event",
        rule="sent when an admin extends a licence's expires_at",
    ),
    "license_revoked": TriggerSpec(
        kind="event",
        rule="sent when an admin revokes a licence (DELETE /api/admin/licenses/{key})",
    ),

    # ── scheduled (daily tick) ──────────────────────────────────────
    "license_expiring": TriggerSpec(
        kind="scheduled",
        rule="sent once, 7 days before a licence's expires_at",
    ),
    "first_time_tips": TriggerSpec(
        kind="scheduled",
        rule="sent once, ~24 hours after a licence's first heartbeat",
    ),
    "feedback_request": TriggerSpec(
        kind="scheduled",
        rule="sent once, 14 days after a licence is issued",
    ),
    "holiday_check_in": TriggerSpec(
        kind="scheduled",
        rule="sent weekly on Sunday to all active licence holders",
    ),

    # ── manual (admin UI only) ──────────────────────────────────────
    "release_announcement": TriggerSpec(
        kind="manual",
        rule="admin-triggered from the emails tab (pair with a new release)",
    ),
    "maintenance_notice": TriggerSpec(
        kind="manual",
        rule="admin-triggered; schedule ahead of planned downtime",
    ),
    "launch_day_announcement": TriggerSpec(
        kind="manual",
        rule="admin-triggered one-off blast on launch day",
    ),
    "incident_notice": TriggerSpec(
        kind="manual",
        rule="admin-triggered when something's broken in production",
    ),
    "feature_spotlight": TriggerSpec(
        kind="manual",
        rule="admin-triggered monthly roundup of shipped features",
    ),
    "account_action_required": TriggerSpec(
        kind="manual",
        rule="admin-triggered generic 'you need to do X' template",
    ),
}


def trigger_for(template_id: str) -> TriggerSpec:
    """Return the trigger spec for ``template_id``, defaulting to manual."""
    return TRIGGERS.get(
        template_id,
        TriggerSpec(kind="manual", rule="no registered trigger — admin-only"),
    )
