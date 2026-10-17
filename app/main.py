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
from .routes import (
    admin_router,
    artist_router,
    auth_router,
    exports_router,
    health_router,
    internal_router,
    jobs_router,
    lab_router,
    models_router,
    projects_router,
    seo_router,
    llm_router,
    styles_router,
    features_router,
    billing_router,
    uploads_router,
    workspaces_router,
)
from .storage import build_storage

API_V1_PREFIX = "/api/v1"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or f"req_{uuid4().hex[:16]}"
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class BodyLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_body_bytes: int, max_upload_bytes: int = 0) -> None:
        super().__init__(app)
        self.max_body_bytes = max_body_bytes
        self.max_upload_bytes = max_upload_bytes

    async def dispatch(self, request: Request, call_next):
        limit = self.max_body_bytes
        if self.max_upload_bytes and (
            request.url.path.endswith("/data")
            or request.url.path.endswith("/upload")
            or request.url.path.endswith("/avatar")
            or request.url.path == "/lab/api/upload"
        ):
            limit = self.max_upload_bytes
        content_length = request.headers.get("Content-Length")
        if content_length is not None and content_length.isdigit():
            if int(content_length) > limit:
                from .errors import _envelope

                return JSONResponse(
                    status_code=413,
                    content=_envelope(
                        request,
                        "BODY_TOO_LARGE",
                        "Request body exceeds the configured limit.",
                        {"max_body_bytes": limit},
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
    app.state.storage = build_storage(settings)
    if settings.llm_base_url:
        from .llm import LlmClient

        app.state.llm = LlmClient(settings.llm_base_url, settings.llm_timeout_seconds)

    app.add_middleware(BodyLimitMiddleware, max_body_bytes=settings.max_body_bytes, max_upload_bytes=settings.max_upload_bytes)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "If-Match"],
        expose_headers=["Location", "Retry-After", "X-Request-ID", "ETag"],
    )
    install_error_handlers(app)

    app.include_router(health_router, prefix=API_V1_PREFIX)
    app.include_router(models_router, prefix=API_V1_PREFIX)
    app.include_router(jobs_router, prefix=API_V1_PREFIX)
    app.include_router(projects_router, prefix=API_V1_PREFIX)
    app.include_router(uploads_router, prefix=API_V1_PREFIX)
    app.include_router(exports_router, prefix=API_V1_PREFIX)
    app.include_router(artist_router, prefix=API_V1_PREFIX)
    app.include_router(auth_router, prefix=API_V1_PREFIX)
    app.include_router(admin_router, prefix=API_V1_PREFIX)
    app.include_router(llm_router, prefix=API_V1_PREFIX)
    app.include_router(styles_router, prefix=API_V1_PREFIX)
    app.include_router(features_router, prefix=API_V1_PREFIX)
    app.include_router(billing_router, prefix=API_V1_PREFIX)
    app.include_router(workspaces_router, prefix=API_V1_PREFIX)
    app.include_router(seo_router)
    app.include_router(internal_router, prefix="/internal/v1")
    # /lab stopgap test harness (self-prefixed routes, HTTP Basic guarded).
    app.include_router(lab_router)
    # Root aliases for container/compose healthchecks.
    app.include_router(health_router, include_in_schema=False)
    _mount_web(app)
    _bootstrap_site(app)
    return app


def _mount_web(app) -> None:
    """Serve the built React shell (SPA fallback) when the bundle is present."""
    from pathlib import Path

    from fastapi.responses import FileResponse, Response
    from fastapi.staticfiles import StaticFiles

    web_dir = Path(app.state.settings.web_dir)
    if not web_dir.is_dir():
        return
    assets = web_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        candidate = (web_dir / full_path).resolve()
        if full_path and candidate.is_file() and candidate.is_relative_to(web_dir.resolve()):
            return FileResponse(candidate)
        meta = _route_meta(app, full_path)
        if meta is None:
            return FileResponse(web_dir / "index.html")
        html = (web_dir / "index.html").read_text(encoding="utf-8")
        injected = (
            f"<title>{meta['title']}</title>"
            f"<meta property=\"og:title\" content=\"{meta['title']}\">"
            f"<meta property=\"og:description\" content=\"{meta['description']}\">"
            + (f"<meta property=\"og:audio\" content=\"{meta['audio']}\">" if meta.get("audio") else "")
        )
        html = html.replace("<title>OpenAudioLab</title>", injected, 1)
        return Response(content=html, media_type="text/html")


def _route_meta(app, full_path: str) -> dict | None:
    """SSR-lite meta for crawlable routes (/artists/<slug>, /tracks/<id>)."""
    from sqlalchemy import select

    from .models import ArtistProfile, Asset, utcnow
    from .tokens import make_token

    parts = full_path.strip("/").split("/")
    try:
        with app.state.db.session() as session:
            if len(parts) == 2 and parts[0] == "artists" and parts[1] != "slug":
                profile = session.execute(
                    select(ArtistProfile).where(
                        ArtistProfile.slug == parts[1], ArtistProfile.deleted_at.is_(None)
                    )
                ).scalar_one_or_none()
                if profile is not None and profile.sharing_policy == "public":
                    return {"title": f"{profile.name} - OpenAudioLab", "description": f"{profile.name} on OpenAudioLab."}
            if len(parts) == 2 and parts[0] == "tracks":
                asset = session.execute(select(Asset).where(Asset.id == parts[1])).scalar_one_or_none()
                if asset is not None and asset.shared:
                    from datetime import timedelta

                    expiry = utcnow() + timedelta(hours=24)
                    token = make_token(app.state.settings.secret_key, asset.id, expiry)
                    title = asset.title or "Track"
                    return {
                        "title": f"{title} - OpenAudioLab",
                        "description": f"{title} - made with OpenAudioLab.",
                        "audio": f"/api/v1/artifacts/{asset.id}/content?token={token}",
                    }
    except Exception:
        return None
    return None


def _bootstrap_site(app) -> None:
    """Seed the site template default and the bootstrap admin account."""
    from sqlalchemy import func, select

    from .auth import hash_password
    from .models import SiteSetting, User
    from .routes.admin import DEFAULT_TEMPLATE

    settings = app.state.settings
    with app.state.db.session() as session:
        if session.get(SiteSetting, "template") is None:
            session.add(SiteSetting(key="template", value=DEFAULT_TEMPLATE))
            session.commit()
        user_count = session.execute(select(func.count()).select_from(User)).scalar_one()
        if user_count == 0 and settings.bootstrap_admin_email and settings.bootstrap_admin_password:
            session.add(
                User(
                    email=settings.bootstrap_admin_email.strip().lower(),
                    username="admin",
                    password_hash=hash_password(settings.bootstrap_admin_password),
                    role="admin",
                )
            )
            session.commit()
