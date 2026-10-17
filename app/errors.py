"""Canonical error envelope: {"error": {"code", "message", "request_id", "details"}}."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

ERROR_ENVELOPE_EXAMPLE = {
    "error": {
        "code": "MODEL_UNAVAILABLE",
        "message": "The requested model is not accepting jobs.",
        "request_id": "req-...",
        "details": {},
    }
}


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


def _envelope(request: Request, code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
            "details": details,
        }
    }


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, exc.code, exc.message, exc.details),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = {
            "errors": [
                {"loc": [str(part) for part in err.get("loc", [])], "msg": err.get("msg", "")}
                for err in exc.errors()
            ]
        }
        return JSONResponse(
            status_code=422,
            content=_envelope(request, "VALIDATION_FAILED", "Request validation failed.", details),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            413: "BODY_TOO_LARGE",
            422: "VALIDATION_FAILED",
            429: "RATE_LIMITED",
        }.get(exc.status_code, "INTERNAL" if exc.status_code >= 500 else "HTTP_ERROR")
        return JSONResponse(
            status_code=exc.status_code,
            content=_envelope(request, code, str(exc.detail), {}),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        try:
            from .errorlog import record_error

            record_error(
                request.app.state.db,
                component="api",
                error_code="INTERNAL",
                message=str(exc) or exc.__class__.__name__,
                exc=exc,
                route=f"{request.method} {request.url.path}",
                http_status=500,
            )
        except Exception:  # noqa: BLE001
            pass
        return JSONResponse(
            status_code=500,
            content=_envelope(request, "INTERNAL", "Internal server error.", {}),
        )
