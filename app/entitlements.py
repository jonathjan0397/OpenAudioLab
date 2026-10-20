"""Server-side paid-model entitlement.

Premium model access comes from the account's server-side paid tier -- the
authoritative ``plan`` column (beginner/pro/premier), which is only ever set by
billing/administrative flows, never by a client header. A credit balance or a
client-supplied label is never sufficient. An explicit cancellation or an expired
billing period revokes entitlement. Guests and free accounts keep Turbo access
and existing limits.
"""

from __future__ import annotations

from .catalog import ModelRelease
from .errors import ApiError
from .models import User, utcnow

# Plans that denote an active paid tier (server-set).
PAID_PLAN_IDS = {"beginner", "pro", "premier"}
# Explicit terminal states that revoke entitlement even if plan still names a tier.
TERMINAL_STATUSES = {"canceled", "cancelled", "unpaid", "incomplete_expired", "incomplete", "expired", "paused"}


def is_premium(release: ModelRelease) -> bool:
    # Turbo is the free/basic family; every other selection is paid.
    return release.family != "turbo"


def has_paid_subscription(user: User | None) -> bool:
    if user is None or user.state != "active":
        return False
    # Administrators may exercise every model for operational testing,
    # independent of their own billing plan.
    if getattr(user, "role", None) == "admin":
        return True
    # The server-set plan is the entitlement source of truth.
    if user.plan not in PAID_PLAN_IDS:
        return False
    status = (user.subscription_status or "").strip().lower()
    if status in TERMINAL_STATUSES:
        return False
    # A recorded billing period must not have lapsed.
    period_end = user.current_period_end
    if period_end is not None:
        end = period_end if period_end.tzinfo else period_end.replace(tzinfo=utcnow().tzinfo)
        if end <= utcnow():
            return False
    # An account with a paid plan but no populated subscription_status (e.g. a
    # tier set administratively or a legacy/pre-prod row) is still entitled as
    # long as it is not terminal and its period has not expired.
    return True


def require_model_access(session, owner_id: str, release: ModelRelease) -> None:
    """Raise 403 when a premium model is requested without a paid entitlement."""
    if not is_premium(release):
        return
    user = None
    if owner_id.startswith("usr_"):
        user = session.get(User, owner_id[4:])
    if not has_paid_subscription(user):
        raise ApiError(
            403,
            "PREMIUM_MODEL_REQUIRES_PAID_PLAN",
            "This model requires an active paid subscription (Beginner or higher).",
            {"model_selection": release.selection, "required": "paid_subscription"},
        )
