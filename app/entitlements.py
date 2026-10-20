"""Server-side paid-model entitlement.

Premium model access comes ONLY from an authenticated account's real paid
subscription (including a valid Beginner period). A credit balance or a
client-supplied plan label is never sufficient. Guests and unsubscribed
accounts keep Turbo access + existing limits.
"""

from __future__ import annotations

from .catalog import ModelRelease
from .errors import ApiError
from .models import User, utcnow

PAID_STATUSES = {"active", "trialing", "canceling"}  # canceling = paid period honored
PAID_PLAN_IDS = {"beginner", "pro", "premier"}


def is_premium(release: ModelRelease) -> bool:
    # Turbo is the free/basic family; every other selection is paid.
    return release.family != "turbo"


def has_paid_subscription(user: User | None) -> bool:
    if user is None or user.state != "active":
        return False
    if user.plan not in PAID_PLAN_IDS:
        return False
    if (user.subscription_status or "") not in PAID_STATUSES:
        return False
    # If a period end is recorded, it must still be in the future.
    period_end = user.current_period_end
    if period_end is not None:
        end = period_end if period_end.tzinfo else period_end.replace(tzinfo=utcnow().tzinfo)
        if end <= utcnow():
            return False
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
            {"model_selection": release.selection, "required": "active_paid_subscription"},
        )
