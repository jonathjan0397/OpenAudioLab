"""Identity: the trusted frontend supplies a per-user bearer token.

The backend performs no user authentication (owner decision 2026-10-15):
the opaque token is hashed into a stable internal owner id used only for
resource isolation. The authenticated owner id comes only from the
credential, never from a request body field.
"""

from __future__ import annotations

import hashlib

from fastapi import Request

from .errors import ApiError


def owner_from_request(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header or not header.lower().startswith("bearer "):
        raise ApiError(401, "UNAUTHENTICATED", "A per-user bearer token is required.")
    token = header[7:].strip()
    if not token or len(token) > 512:
        raise ApiError(401, "UNAUTHENTICATED", "A per-user bearer token is required.")
    return "tok_" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]
