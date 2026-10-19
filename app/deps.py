"""Identity: account sessions, registered API keys, and server-issued guests.

The public API no longer accepts arbitrary bearer strings as owners. A bearer
credential must resolve to an active registered API key. Cookie requests may
resolve to an account session first, then to a server-issued guest session.
"""

from __future__ import annotations

from fastapi import Request
from sqlalchemy import select

from .errors import ApiError


def _api_key_owner(request: Request, token: str) -> str:
    from .auth import token_sha256
    from .models import ApiKey, utcnow

    digest = token_sha256(token)
    with request.app.state.db.session() as session:
        key = session.execute(
            select(ApiKey).where(ApiKey.key_sha256 == digest, ApiKey.revoked_at.is_(None))
        ).scalar_one_or_none()
        if key is None:
            raise ApiError(401, "CREDENTIAL_INVALID", "Bearer API key is unknown, expired, or revoked.")
        key.last_used_at = utcnow()
        session.commit()
        return key.owner_id


def _user_owner_from_cookie(request: Request) -> str | None:
    from .auth import COOKIE_NAME, token_sha256
    from .models import User, UserSession, utcnow
    from .orchestration import as_utc

    cookie = request.cookies.get(COOKIE_NAME)
    if not cookie:
        return None
    with request.app.state.db.session() as session:
        record = session.execute(
            select(UserSession).where(UserSession.token_sha256 == token_sha256(cookie))
        ).scalar_one_or_none()
        if record is None or as_utc(record.expires_at) <= utcnow():
            return None
        user = session.get(User, record.user_id)
        if user is None or user.state != "active":
            return None
        return "usr_" + user.id


def guest_session_from_request(request: Request):
    from .auth import token_sha256
    from .models import GuestSession, utcnow
    from .orchestration import as_utc

    cookie = request.cookies.get(request.app.state.settings.guest_cookie_name)
    if not cookie:
        return None
    with request.app.state.db.session() as session:
        guest = session.execute(
            select(GuestSession).where(GuestSession.token_sha256 == token_sha256(cookie))
        ).scalar_one_or_none()
        if guest is None or as_utc(guest.expires_at) <= utcnow():
            return None
        guest.last_seen_at = utcnow()
        session.commit()
        session.expunge(guest)
        return guest


def _guest_owner_from_cookie(request: Request) -> str | None:
    guest = guest_session_from_request(request)
    return f"g_{guest.id}" if guest is not None else None


def owner_from_request(request: Request) -> str:
    header = request.headers.get("Authorization")
    if header and header.lower().startswith("bearer "):
        token = header[7:].strip()
        if not token or len(token) > 512:
            raise ApiError(401, "UNAUTHENTICATED", "A registered bearer API key is required.")
        return _api_key_owner(request, token)

    user_owner = _user_owner_from_cookie(request)
    if user_owner is not None:
        return user_owner
    guest_owner = _guest_owner_from_cookie(request)
    if guest_owner is not None:
        return guest_owner
    raise ApiError(401, "UNAUTHENTICATED", "A session cookie or registered bearer API key is required.")
