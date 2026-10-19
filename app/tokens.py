"""Short-lived signed download tokens (no long-lived secrets in URLs)."""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone


def make_token(secret: str, asset_id: str, expires_at: datetime) -> str:
    epoch = int(expires_at.timestamp())
    payload = f"{asset_id}.{epoch}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{epoch}.{signature}"


def check_token(secret: str, asset_id: str, token: str, now: datetime) -> datetime | None:
    """Return the token expiry (UTC) when valid, else None."""
    try:
        epoch_text, signature = token.split(".", 1)
        epoch = int(epoch_text)
    except (ValueError, AttributeError):
        return None
    payload = f"{asset_id}.{epoch}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(signature, expected):
        return None
    expiry = datetime.fromtimestamp(epoch, tz=timezone.utc)
    if now > expiry:
        return None
    return expiry
