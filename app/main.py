"""FastAPI application factory. Control-plane only: no model weights here."""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import Settings, get_settings
from .db import Db
from .errors import install_error_handlers
from .routes import health_router, jobs_router, models_router
from .storage import LocalObjectStorage

API_V1_PREFIX = "/api/v1"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or f"req_{uuid4().hex[:16]}"
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class BodyLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_body_bytes: int) -> None:
        super().__init__(app)
        self.max_body_bytes = max_body_bytes

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("Content-Length")
        if content_length is not None and content_length.isdigit():
            if int(content_length) > self.max_body_bytes:
                from .errors import _envelope

                return JSONResponse(
                    status_code=413,
                    content=_envelope(
                        request,
                        "BODY_TOO_LARGE",
                        "Request body exceeds the configured limit.",
                        {"max_body_bytes": self.max_body_bytes},
                    ),
                )
        return await call_next(request)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0-m1",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    app.state.db = Db(settings.database_url)
    app.state.storage = LocalObjectStorage(settings.storage_dir)

    app.add_middleware(BodyLimitMiddleware, max_body_bytes=settings.max_body_bytes)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        expose_headers=["Location", "Retry-After", "X-Request-ID"],
    )
    install_error_handlers(app)

    app.include_router(health_router, prefix=API_V1_PREFIX)
    app.include_router(models_router, prefix=API_V1_PREFIX)
    app.include_router(jobs_router, prefix=API_V1_PREFIX)
    # Root aliases for container/compose healthchecks.
    app.include_router(health_router, include_in_schema=False)
    return app
