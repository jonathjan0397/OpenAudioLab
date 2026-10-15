"""Liveness and dependency readiness. Public, no bearer token."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from ..errors import ApiError

router = APIRouter(tags=["health"])


@router.get("/health/live")
def health_live() -> dict[str, str]:
    return {"status": "live"}


@router.get("/health/ready")
def health_ready(request: Request) -> JSONResponse:
    db = request.app.state.db
    try:
        with db.session() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        raise ApiError(503, "NOT_READY", "A required dependency is unavailable.")
    return JSONResponse(status_code=200, content={"status": "ready"})
