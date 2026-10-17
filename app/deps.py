"""Identity: the trusted frontend supplies a per-user bearer token.

The backend performs no user authentication (owner decision 2026-10-15):
the opaque token is hashed into a stable internal owner id used only for
resource isolation. The authenticated owner id comes only from the
credential, never from a request body field.
"""

from __future__ import annotations

import hashlib

from fastapi import Request
from sqlalchemy import select

from .errors import ApiError


def owner_from_request(request: Request) -> str:
    header = request.headers.get("Authorization")
    if header and header.lower().startswith("bearer "):
        token = header[7:].strip()
        if token and len(token) <= 512:
            from .auth import token_sha256
            from .models import ApiKey, utcnow

            digest = token_sha256(token)
            with request.app.state.db.session() as session:
                key = session.execute(
                    select(ApiKey).where(ApiKey.key_sha256 == digest, ApiKey.revoked_at.is_(None))
                ).scalar_one_or_none()
                if key is not None:
                    key.last_used_at = utcnow()
                    session.commit()
                    return key.owner_id
            return "tok_" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
        raise ApiError(401, "UNAUTHENTICATED", "A per-user bearer token is required.")
    # Cookie-session fallback for the website.
    from .auth import COOKIE_NAME, token_sha256
    from .models import User, UserSession, utcnow
    from .orchestration import as_utc

    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        with request.app.state.db.session() as session:
            record = session.execute(
                select(UserSession).where(UserSession.token_sha256 == token_sha256(cookie))
            ).scalar_one_or_none()
            if record is not None and as_utc(record.expires_at) > utcnow():
                user = session.get(User, record.user_id)
                if user is not None and user.state == "active":
                    return "usr_" + user.id
    raise ApiError(401, "UNAUTHENTICATED", "A per-user bearer token is required.")
