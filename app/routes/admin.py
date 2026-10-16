"""Admin controls: user management + site settings (template switch)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from ..errors import ApiError
from ..models import SiteSetting, User, utcnow
from .auth import require_admin, user_payload

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin)])

ALLOWED_TEMPLATES = ("open-canvas", "analog-soul", "neon-studio", "signal-lab")
DEFAULT_TEMPLATE = "open-canvas"


class AdminCreateUser(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    username: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=200)
    role: str = Field(default="user", pattern=r"^(user|admin)$")


class AdminPatchUser(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(user|admin)$")
    state: str | None = Field(default=None, pattern=r"^(active|disabled)$")
    credits_balance: int | None = Field(default=None, ge=0)


class TemplateSetting(BaseModel):
    value: str = Field(pattern=r"^[a-z-]+$")


@router.get("/admin/users")
def admin_list_users(
    request: Request,
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    with request.app.state.db.session() as session:
        stmt = select(User)
        if q:
            like = f"%{q.strip().lower()}%"
            stmt = stmt.where(or_(func.lower(User.email).like(like), func.lower(User.username).like(like)))
        total = session.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()
        rows = list(
            session.execute(stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)).scalars()
        )
    return JSONResponse({"users": [user_payload(u) for u in rows], "total": total})


@router.post("/admin/users", status_code=201)
def admin_create_user(payload: AdminCreateUser, request: Request) -> JSONResponse:
    from ..auth import hash_password

    email = payload.email.strip().lower()
    with request.app.state.db.session() as session:
        if session.execute(select(User).where(User.email == email)).scalar_one_or_none():
            raise ApiError(409, "EMAIL_TAKEN", "Email already registered.")
        if session.execute(select(User).where(User.username == payload.username)).scalar_one_or_none():
            raise ApiError(409, "USERNAME_TAKEN", "Username already taken.")
        user = User(
            email=email,
            username=payload.username,
            password_hash=hash_password(payload.password),
            role=payload.role,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
    return JSONResponse(status_code=201, content={"user": user_payload(user)})


@router.patch("/admin/users/{user_id}")
def admin_patch_user(user_id: str, payload: AdminPatchUser, request: Request) -> JSONResponse:
    with request.app.state.db.session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "User not found.")
        if payload.role is not None:
            user.role = payload.role
        if payload.state is not None:
            user.state = payload.state
        if payload.credits_balance is not None:
            user.credits_balance = payload.credits_balance
        user.updated_at = utcnow()
        session.commit()
        session.refresh(user)
    return JSONResponse(content={"user": user_payload(user)})


@router.get("/admin/settings")
def admin_get_settings(request: Request) -> JSONResponse:
    with request.app.state.db.session() as session:
        rows = list(session.execute(select(SiteSetting)).scalars())
    return JSONResponse({"settings": {row.key: row.value for row in rows}})


@router.put("/admin/settings/template")
def admin_put_template(payload: TemplateSetting, request: Request) -> JSONResponse:
    if payload.value not in ALLOWED_TEMPLATES:
        raise ApiError(
            422,
            "TEMPLATE_UNKNOWN",
            "Unknown site template.",
            {"allowed": list(ALLOWED_TEMPLATES)},
        )
    with request.app.state.db.session() as session:
        row = session.get(SiteSetting, "template")
        if row is None:
            session.add(SiteSetting(key="template", value=payload.value))
        else:
            row.value = payload.value
        session.commit()
    return JSONResponse(content={"template": payload.value})


@router.get("/admin/stats")
def admin_stats(request: Request) -> JSONResponse:
    from datetime import timedelta

    from sqlalchemy import func as sa_func

    from ..models import Asset, Job, User, Worker, utcnow as _utcnow

    now = utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=0)
    with request.app.state.db.session() as session:
        users_total = session.execute(select(sa_func.count()).select_from(User)).scalar_one()
        jobs_today = session.execute(
            select(sa_func.count()).select_from(Job).where(Job.created_at >= day_start)
        ).scalar_one()
        jobs_active = session.execute(
            select(sa_func.count()).select_from(Job).where(
                Job.status.in_(("queued", "waiting_for_worker", "running"))
            )
        ).scalar_one()
        assets_total = session.execute(
            select(sa_func.count()).select_from(Asset).where(
                Asset.deleted_at.is_(None), Asset.mime.like("audio/%")
            )
        ).scalar_one()
        workers = list(session.execute(select(Worker)).scalars())
    return JSONResponse(
        {
            "users_total": users_total,
            "jobs_today": jobs_today,
            "jobs_active": jobs_active,
            "assets_total": assets_total,
            "workers": [
                {
                    "id": w.id,
                    "kind": w.kind,
                    "drain": w.drain,
                    "last_heartbeat": w.last_heartbeat.isoformat() if w.last_heartbeat else None,
                }
                for w in workers
            ],
        }
    )
