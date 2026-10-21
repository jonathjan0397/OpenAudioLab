"""Admin controls: user management + site settings (template switch)."""

from __future__ import annotations

import re
import urllib.parse
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from ..errors import ApiError
from ..models import SiteSetting, User, utcnow
from .auth import require_admin, user_payload

router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin)])

ALLOWED_TEMPLATES = ("open-canvas", "analog-soul", "neon-studio", "signal-lab")
DEFAULT_TEMPLATE = "open-canvas"
TRASH_PURGE_HOURS = 48

_MIME_EXT = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/flac": ".flac",
    "audio/ogg": ".ogg",
    "application/zip": ".zip",
}


def _filename_ext(asset) -> str:
    from ..naming import filename_ext

    return filename_ext(asset.mime, asset.storage_key)


def _safe_filename(base: str | None, asset_id: str) -> str:
    from ..naming import safe_filename

    return safe_filename(base, asset_id)


def _disposition(asset) -> str:
    from ..naming import asset_disposition

    return asset_disposition(asset)


def _asset_state(asset, now) -> str:
    from ..orchestration import as_utc

    if asset.purged_at is not None:
        return "purged"
    if asset.deleted_at is not None:
        return "trashed"
    if asset.expires_at is not None and as_utc(asset.expires_at) <= now:
        return "expired"
    if asset.shared:
        return "shared"
    return "live"


class AdminCreateUser(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    username: str = Field(min_length=2, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=200)
    role: str = Field(default="user", pattern=r"^(user|admin)$")


class AdminPatchUser(BaseModel):
    role: str | None = Field(default=None, pattern=r"^(user|admin)$")
    state: str | None = Field(default=None, pattern=r"^(active|disabled)$")
    credits_balance: int | None = Field(default=None, ge=0)
    plan: str | None = Field(default=None, pattern=r"^(free|beginner|pro|premier)$")


class AdminCreditAdjust(BaseModel):
    delta: int = Field(ge=-1_000_000, le=1_000_000)
    reason: str = Field(default="admin_adjust", max_length=60)
    note: str | None = Field(default=None, max_length=200)


class AdminAssetPatch(BaseModel):
    shared: bool | None = Field(default=None)
    trash: bool | None = Field(default=None)


class TemplateSetting(BaseModel):
    value: str = Field(pattern=r"^[a-z-]+$")


def _revenue(session) -> float:
    from .billing import subscription_revenue

    return subscription_revenue(session)


@router.get("/admin/users")
def admin_list_users(
    request: Request,
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    with request.app.state.db.session() as session:
        stmt = select(User).where(User.deleted_at.is_(None))
        if q:
            like = f"%{q.strip().lower()}%"
            stmt = stmt.where(or_(func.lower(User.email).like(like), func.lower(User.username).like(like)))
        total = session.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()
        rows = list(
            session.execute(stmt.order_by(User.created_at.desc()).limit(limit).offset(offset)).scalars()
        )
        from ..models import Job

        owner_ids = ["usr_" + u.id for u in rows]
        counts: dict[str, int] = {}
        if owner_ids:
            for oid, cnt in session.execute(
                select(Job.owner_id, func.count()).where(Job.owner_id.in_(owner_ids)).group_by(Job.owner_id)
            ).all():
                counts[oid] = int(cnt)
    return JSONResponse(
        {
            "users": [{**user_payload(u), "jobs_count": counts.get("usr_" + u.id, 0)} for u in rows],
            "total": total,
        }
    )


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
def admin_patch_user(
    user_id: str,
    payload: AdminPatchUser,
    request: Request,
    admin: User = Depends(require_admin),
) -> JSONResponse:
    from ..audit import record_admin_audit

    with request.app.state.db.session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "User not found.")
        changes = payload.model_dump(exclude_none=True)
        if payload.role is not None:
            user.role = payload.role
        if payload.state is not None:
            user.state = payload.state
        if payload.credits_balance is not None:
            user.credits_balance = payload.credits_balance
        if payload.plan is not None:
            user.plan = payload.plan
        user.updated_at = utcnow()
        record_admin_audit(session, admin.id, "user.patch", "user", user.id, context_json=changes)
        session.commit()
        session.refresh(user)
    return JSONResponse(content={"user": user_payload(user)})


@router.get("/admin/settings")
def admin_get_settings(request: Request) -> JSONResponse:
    with request.app.state.db.session() as session:
        rows = list(session.execute(select(SiteSetting)).scalars())
    return JSONResponse(
        {
            "settings": {row.key: row.value for row in rows},
            "billing_mode": getattr(request.app.state.settings, "billing_mode", "production"),
        }
    )


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
        storage_bytes = session.execute(
            select(sa_func.coalesce(sa_func.sum(Asset.bytes), 0)).where(Asset.deleted_at.is_(None))
        ).scalar_one()
        workers = list(session.execute(select(Worker)).scalars())
        yesterday_start = day_start - timedelta(days=1)
        jobs_yesterday = session.execute(
            select(sa_func.count()).select_from(Job).where(
                Job.created_at >= yesterday_start, Job.created_at < day_start
            )
        ).scalar_one()
        active_30 = session.execute(
            select(sa_func.count(sa_func.distinct(Job.owner_id))).select_from(Job).where(
                Job.created_at >= now - timedelta(days=30)
            )
        ).scalar_one()
        active_prev = session.execute(
            select(sa_func.count(sa_func.distinct(Job.owner_id))).select_from(Job).where(
                Job.created_at >= now - timedelta(days=60), Job.created_at < now - timedelta(days=30)
            )
        ).scalar_one()
        from ..models import CreditEntry

        credits_used = session.execute(
            select(sa_func.coalesce(sa_func.sum(-CreditEntry.delta), 0)).where(CreditEntry.delta < 0)
        ).scalar_one()
        revenue = _revenue(session)
    gpu_utils = [
        w.gpu_util for w in workers
        if w.gpu_util is not None and w.last_heartbeat and (now - w.last_heartbeat).total_seconds() < 120
    ]
    return JSONResponse(
        {
            "users_total": users_total,
            "active_users_30d": int(active_30),
            "active_users_prev_30d": int(active_prev),
            "jobs_today": jobs_today,
            "jobs_yesterday": jobs_yesterday,
            "jobs_active": jobs_active,
            "assets_total": assets_total,
            "storage_bytes": int(storage_bytes),
            "gpu_util_avg": round(sum(gpu_utils) / len(gpu_utils)) if gpu_utils else None,
            "revenue": revenue,
            "credits_used": int(credits_used),
            "credits_quota": 1_000_000,
            "workers": [
                {
                    "id": w.id,
                    "kind": w.kind,
                    "drain": w.drain,
                    "gpu_util": w.gpu_util,
                    "vram_used_mb": w.vram_used_mb,
                    "vram_total_mb": w.vram_total_mb,
                    "last_heartbeat": w.last_heartbeat.isoformat() if w.last_heartbeat else None,
                }
                for w in workers
            ],
        }
    )


@router.get("/admin/stats/timeseries")
def admin_timeseries(
    request: Request,
    days: int = Query(default=14, ge=1, le=90),
    granularity: str = Query(default="day", pattern="^(day|hour)$"),
    task: str = Query(default="all", pattern="^(all|generate|export|training)$"),
) -> JSONResponse:
    """Job counts by status + new users per bucket, for admin charts.

    granularity=hour returns the last 24 hours; task filters by operation family.
    """
    from datetime import timedelta

    from ..models import Job

    op_filter = {
        "generate": "music.generate",
        "export": "audio.export",
        "training": "voice.train",
    }.get(task if task != "all" else "", None)

    if granularity == "hour":
        hours = 24
        start = utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(hours=hours - 1)
    else:
        hours = 0
        start = utcnow() - timedelta(days=days - 1)
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    with request.app.state.db.session() as session:
        job_stmt = select(Job.created_at, Job.status).where(Job.created_at >= start)
        if op_filter:
            job_stmt = job_stmt.where(Job.operation == op_filter)
        job_rows = session.execute(job_stmt).all()
        user_rows = session.execute(
            select(User.created_at).where(User.created_at >= start)
        ).scalars().all()
    buckets: dict[str, dict] = {}
    span = hours if granularity == "hour" else days
    step = timedelta(hours=1) if granularity == "hour" else timedelta(days=1)
    for offset in range(span):
        point = start + step * offset
        key = point.strftime("%Y-%m-%dT%H" if granularity == "hour" else "%Y-%m-%d")
        buckets[key] = {"date": key, "completed": 0, "failed": 0, "cancelled": 0, "active": 0, "new_users": 0}
    for created, status in job_rows:
        key = created.strftime("%Y-%m-%dT%H" if granularity == "hour" else "%Y-%m-%d")
        bucket = buckets.get(key)
        if bucket is None:
            continue
        if status == "succeeded":
            bucket["completed"] += 1
        elif status == "failed":
            bucket["failed"] += 1
        elif status == "cancelled":
            bucket["cancelled"] += 1
        elif status in ("queued", "waiting_for_worker", "running"):
            bucket["active"] += 1
    for created in user_rows:
        key = created.strftime("%Y-%m-%dT%H" if granularity == "hour" else "%Y-%m-%d")
        if key in buckets:
            buckets[key]["new_users"] += 1
    return JSONResponse({"days": days, "granularity": granularity, "task": task, "series": list(buckets.values())})


TASK_LABELS = {
    "music.generate": "Text to Music",
    "audio.export": "Audio Export",
    "voice.train": "Voice Training",
    "voice.analyze": "Voice Analysis",
    "voice.validate": "Voice Validation",
}


@router.get("/admin/jobs")
def admin_jobs(
    request: Request,
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None, max_length=30),
    task: str | None = Query(default=None, max_length=40),
) -> JSONResponse:
    """Most recent jobs across all owners, with user + task labels."""
    from ..models import Job

    with request.app.state.db.session() as session:
        stmt = select(Job)
        if status:
            stmt = stmt.where(Job.status == status)
        if task:
            stmt = stmt.where(Job.operation == task)
        total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = list(
            session.execute(stmt.order_by(Job.created_at.desc()).limit(limit).offset(offset)).scalars()
        )
        user_ids = sorted({j.owner_id[4:] for j in rows if j.owner_id.startswith("usr_")})
        names = {}
        if user_ids:
            for u in session.execute(select(User).where(User.id.in_(user_ids))).scalars():
                names["usr_" + u.id] = u.username
    out = []
    for j in rows:
        runtime = None
        if j.started_at and j.finished_at:
            runtime = max(0.0, (j.finished_at - j.started_at).total_seconds())
        out.append(
            {
                "job_id": j.id,
                "owner_id": j.owner_id,
                "user": names.get(j.owner_id, j.owner_id.replace("tok_", "api:")[:14]),
                "operation": j.operation,
                "task": TASK_LABELS.get(j.operation, j.operation),
                "status": j.status,
                "stage": j.stage,
                "progress": j.progress,
                "error_code": j.error_code,
                "runtime_seconds": runtime,
                "created_at": j.created_at.isoformat() if j.created_at else None,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "finished_at": j.finished_at.isoformat() if j.finished_at else None,
            }
        )
    return JSONResponse({"items": out, "total": total})


@router.get("/admin/trainings")
def admin_trainings(request: Request, limit: int = Query(default=5, ge=1, le=50)) -> JSONResponse:
    """Recent UAIS voice jobs with live progress, for the admin overview."""
    from ..models import ArtistProfile, Job, VoiceAdapter

    with request.app.state.db.session() as session:
        rows = list(
            session.execute(
                select(Job, ArtistProfile.name, User.username, VoiceAdapter)
                .outerjoin(VoiceAdapter, VoiceAdapter.training_job_id == Job.id)
                .outerjoin(ArtistProfile, ArtistProfile.id == VoiceAdapter.artist_profile_id)
                .outerjoin(User, User.id == func.replace(Job.owner_id, "usr_", ""))
                .where(Job.operation.in_(("voice.analyze", "voice.train", "voice.validate")))
                .order_by(Job.seq.desc())
                .limit(limit)
            ).all()
        )
    out = []
    for job, name, username, adapter in rows:
        eta = None
        if job.status == "running" and job.progress and job.started_at:
            elapsed = (utcnow() - job.started_at).total_seconds()
            eta = round(elapsed * (1 - job.progress) / job.progress)
        out.append(
            {
                "run_id": job.id,
                "profile": name or "unnamed",
                "adapter_id": adapter.id if adapter else None,
                "model_selection": adapter.model_selection if adapter else None,
                "user": username or "—",
                "status": job.status,
                "operation": job.operation,
                "stage": job.stage,
                "progress": job.progress,
                "eta_seconds": eta,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "hardware": (adapter.metrics_json or {}).get("hardware") if adapter else None,
                "error": f"{job.error_code}: {job.error_message}"[:200] if job.error_code or job.error_message else None,
            }
        )
    return JSONResponse(out)


@router.get("/admin/services")
def admin_services(request: Request) -> JSONResponse:
    """Model service health: 24h requests, latency, success rate per operation family."""
    from datetime import timedelta

    from ..models import Job

    since = utcnow() - timedelta(hours=24)
    services = [
        ("Music Engine 01", "Text to Music", "music.generate", "v1.5", 99.9),
        ("Stem Separator", "Audio Processing", "audio.export", "v1.0", 99.8),
        ("Artist Trainer", "Custom Model Training", "voice.train", "v0.9", 99.5),
    ]
    with request.app.state.db.session() as session:
        rows = session.execute(
            select(
                Job.operation,
                Job.status,
                Job.started_at,
                Job.finished_at,
                Job.created_at,
            ).where(Job.created_at >= since)
        ).all()
    stats: dict[str, dict] = {}
    for operation, status, started, finished, _created in rows:
        st = stats.setdefault(operation, {"requests": 0, "succeeded": 0, "failed": 0, "active": 0, "latencies": []})
        st["requests"] += 1
        if status == "succeeded":
            st["succeeded"] += 1
        elif status == "failed":
            st["failed"] += 1
        elif status in ("queued", "waiting_for_worker", "running"):
            st["active"] += 1
        if started and finished:
            st["latencies"].append((finished - started).total_seconds())
    out = []
    for name, kind, operation, version, uptime in services:
        st = stats.get(operation, {"requests": 0, "succeeded": 0, "failed": 0, "active": 0, "latencies": []})
        done = st["succeeded"] + st["failed"]
        out.append(
            {
                "name": name,
                "kind": kind,
                "operation": operation,
                "version": version,
                "status": "busy" if st["active"] > 0 else "healthy",
                "requests_24h": st["requests"],
                "avg_latency_seconds": round(sum(st["latencies"]) / len(st["latencies"]), 1) if st["latencies"] else None,
                "success_rate": round(st["succeeded"] / done * 100, 1) if done else None,
                "uptime_pct": uptime,
            }
        )
    return JSONResponse({"services": out})


@router.get("/admin/storage")
def admin_storage(request: Request) -> JSONResponse:
    """Storage usage split by category, against the configured quota."""
    from sqlalchemy import func as sa_func

    from ..models import Asset

    settings = request.app.state.settings
    with request.app.state.db.session() as session:
        rows = session.execute(
            select(Asset.role, Asset.kind, sa_func.coalesce(sa_func.sum(Asset.bytes), 0))
            .where(Asset.deleted_at.is_(None))
            .group_by(Asset.role, Asset.kind)
        ).all()
    generated = uploads = other = 0
    for role, kind, size in rows:
        if kind == "uploaded" or role in ("source_upload", "reference"):
            uploads += size
        elif role in ("mix_wav", "mix_mp3", "stems_wav", "stems_zip"):
            generated += size
        else:
            other += size
    total = generated + uploads + other
    return JSONResponse(
        {
            "total_bytes": int(total),
            "quota_bytes": settings.admin_storage_quota_bytes,
            "categories": {
                "generated_audio": int(generated),
                "training_data": int(uploads),
                "model_checkpoints": int(other),
                "other": 0,
            },
        }
    )


@router.get("/admin/billing")
def admin_billing(request: Request) -> JSONResponse:
    """Billing & credits overview (revenue is illustrative until real plans)."""
    from sqlalchemy import func as sa_func

    from ..models import BillingEvent, CreditEntry

    settings = request.app.state.settings
    from ..models import Job as _Job
    from ..models import User as _User

    with request.app.state.db.session() as session:
        credits_used = session.execute(
            select(sa_func.coalesce(sa_func.sum(-CreditEntry.delta), 0)).where(CreditEntry.delta < 0)
        ).scalar_one()
        granted = session.execute(
            select(sa_func.coalesce(sa_func.sum(CreditEntry.delta), 0)).where(CreditEntry.delta > 0)
        ).scalar_one()
        users_total = session.execute(select(sa_func.count()).select_from(_User)).scalar_one()
        subscribers = session.execute(
            select(sa_func.count()).select_from(_User).where(_User.plan != "free")
        ).scalar_one()
        op_rows = session.execute(
            select(_Job.operation, sa_func.count()).group_by(_Job.operation)
        ).all()
        revenue = _revenue(session)
        events = list(
            session.execute(
                select(BillingEvent).order_by(BillingEvent.created_at.desc()).limit(20)
            ).scalars()
        )
    op_counts = {op: int(n) for op, n in op_rows}
    ops_total = sum(op_counts.values())
    pct = lambda op: round(op_counts.get(op, 0) / ops_total * 100, 1) if ops_total else 0
    # Signup grants are a column default, not ledger entries; count them explicitly.
    granted_total = int(granted) + users_total * 1000
    used = int(credits_used)
    quota = 1_000_000
    return JSONResponse(
        {
            "revenue": revenue,
            "revenue_delta_pct": 0,
            "subscribers": int(subscribers),
            "credits_used": used,
            "credits_granted": granted_total,
            "credits_quota": quota,
            "credits_pct": round(used / quota * 100, 1),
            "subscriptions_pct": 0,
            "api_usage_pct": pct("music.generate"),
            "custom_training_pct": pct("voice.train"),
            "export_pct": pct("audio.export"),
            "job_counts": op_counts,
            "billing_mode": getattr(settings, "billing_mode", "production"),
            "events": [
                {
                    "id": e.id,
                    "owner_id": e.owner_id,
                    "event_type": e.event_type,
                    "kind": e.kind,
                    "item_id": e.item_id,
                    "amount_usd": e.amount_usd,
                    "credits": e.credits,
                    "status": e.status,
                    "stripe_event_id": e.stripe_event_id,
                    "invoice_id": e.invoice_id,
                    "subscription_id": e.subscription_id,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in events
            ],
        }
    )


@router.get("/admin/audit")
def admin_audit(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    event: str | None = Query(default=None, max_length=40),
) -> JSONResponse:
    """Recent job lifecycle events across the platform."""
    from ..models import Job, JobEvent

    with request.app.state.db.session() as session:
        stmt = select(JobEvent)
        if event:
            stmt = stmt.where(JobEvent.event == event)
        total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = list(
            session.execute(
                select(JobEvent, Job.owner_id, Job.operation)
                .join(Job, Job.id == JobEvent.job_id)
                .where(*([JobEvent.event == event] if event else []))
                .order_by(JobEvent.id.desc())
                .limit(limit)
                .offset(offset)
            ).all()
        )
    return JSONResponse(
        {
            "items": [
                {
                    "event": ev.event,
                    "status": ev.status,
                    "stage": ev.stage,
                    "job_id": ev.job_id,
                    "owner_id": owner,
                    "operation": operation,
                    "created_at": ev.created_at.isoformat() if ev.created_at else None,
                }
                for ev, owner, operation in rows
            ],
            "total": total,
        }
    )


_OFFER_CACHE: dict = {"key": None, "at": 0.0, "result": None}


def _fleet_settings(request: Request) -> dict:
    import json

    from ..fleet_settings import FLEET_DEFAULTS
    from ..models import SiteSetting

    merged = dict(FLEET_DEFAULTS)
    with request.app.state.db.session() as session:
        row = session.get(SiteSetting, "gpu_fleet_settings")
    if row and row.value:
        try:
            merged.update(json.loads(row.value))
        except ValueError:
            pass
    return merged


@router.get("/admin/gpu-fleet/settings")
def gpu_fleet_settings_get(request: Request) -> JSONResponse:
    from ..fleet_settings import FLEET_DEFAULTS

    return JSONResponse({"settings": _fleet_settings(request), "defaults": FLEET_DEFAULTS})


@router.patch("/admin/gpu-fleet/settings")
def gpu_fleet_settings_patch(request: Request, payload: dict) -> JSONResponse:
    import json

    from ..fleet_settings import SETTINGS_KEY, FleetSettingsError, validate
    from ..models import GpuFleetEvent, SiteSetting, new_uuid

    try:
        merged = validate(payload)
    except FleetSettingsError as exc:
        raise ApiError(422, "FLEET_SETTING_INVALID", str(exc)) from exc
    admin = payload.get("_actor") or "admin"
    with request.app.state.db.session() as session:
        row = session.get(SiteSetting, SETTINGS_KEY)
        if row is None:
            row = SiteSetting(key=SETTINGS_KEY, value=json.dumps(merged))
            session.add(row)
        else:
            row.value = json.dumps(merged)
        session.add(GpuFleetEvent(id=new_uuid(), actor=str(admin), action="settings_patch",
                                  subject=SETTINGS_KEY, detail_json={"changed": sorted(payload.keys())}))
        session.commit()
    return JSONResponse({"settings": merged})


@router.get("/admin/gpu-fleet/offers")
def gpu_fleet_offers(
    request: Request,
    model: str | None = None,
    max_dph: float | None = None,
    min_vram: int | None = None,
    country: str | None = None,
    min_reliability: float | None = None,
    min_download: float | None = None,
    min_upload: float | None = None,
    verified: bool = True,
    refresh: bool = False,
) -> JSONResponse:
    """Top-10 live Vast.ai offers (advisory snapshots, 30 s server cache)."""
    import json as _json
    import time

    import requests as _requests

    from .. import vast_offers as vo
    from ..catalog import CATALOG

    settings = request.app.state.settings
    stored = _fleet_settings(request)
    crit = {
        "max_dph": min(max_dph if max_dph is not None else stored["max_dph"], 1.0),
        "min_vram_gb": min_vram if min_vram is not None else stored["min_vram_gb"],
        "countries": [country.upper()] if country else list(stored["countries"]),
        "min_reliability": min_reliability if min_reliability is not None else stored["min_reliability"],
        "min_download_mbps": min_download,
        "min_upload_mbps": min_upload,
        "verified_only": verified,
        "min_cuda": stored["min_cuda"],
        "model_vram_floor_gb": 0,
        "checkpoint_gb": 0.0,
    }
    if model:
        prof = None
        for release in CATALOG.values():
            prof = release.profile(model)
            if prof is not None:
                break
        if prof is None:
            raise ApiError(422, "MODEL_UNKNOWN", f"Unknown execution profile: {model}")
        crit["model_vram_floor_gb"] = max(0, prof.vram_required_mb // 1024)
        crit["checkpoint_gb"] = vo.CHECKPOINT_GB.get(prof.native_family, 5.0)
        crit["min_compute_cap"] = 7.5
    key = _json.dumps(crit, sort_keys=True)
    cache = _OFFER_CACHE
    if not refresh and cache["key"] == key and time.time() - cache["at"] < 30:
        result = cache["result"]
        return JSONResponse({**result, "cached": True})
    query = {"search": {
        "rentable": {"eq": True},
        "cuda_max_good": {"gte": crit["min_cuda"]},
        "gpu_ram": {"gte": int(crit["min_vram_gb"] * 1024 * 1024 * 1024)},
        "num_gpus": {"eq": 1},
        "dph_total": {"lte": crit["max_dph"]},
    }}
    if crit["verified_only"]:
        query["search"]["verification"] = {"eq": "verified"}
    try:
        resp = _requests.post(f"{settings.vast_api_url}/search/offers/", json=query, timeout=20)
        resp.raise_for_status()
        raw = resp.json().get("matches", [])
    except Exception as exc:
        raise ApiError(502, "VAST_SEARCH_FAILED", f"Vast.ai offer search failed: {exc}") from exc
    result = vo.rank(raw, crit, limit=10)
    result["refreshed_at"] = utcnow().isoformat()
    cache.update({"key": key, "at": time.time(), "result": result})
    return JSONResponse({**result, "cached": False})


@router.get("/admin/gpu-fleet/queues")
def gpu_fleet_queues(request: Request) -> JSONResponse:
    """SMQM view: waiting jobs per model group (DB-authoritative), worker
    loaded checkpoints, and Redis delivery-hint depths."""
    from ..models import Job, Worker
    from ..orchestration import as_utc

    settings = request.app.state.settings
    now = utcnow()
    with request.app.state.db.session() as session:
        rows = session.execute(
            select(Job.request_json, Job.created_at).where(
                Job.operation == "music.generate", Job.status == "queued"
            )
        ).all()
        workers = list(
            session.execute(
                select(Worker).where(Worker.kind == "acestep").order_by(Worker.last_heartbeat.desc())
            ).scalars()
        )
    by_model: dict[str, dict] = {}
    for rjson, created in rows:
        adm = (rjson or {}).get("_admission") or {}
        fam = adm.get("family") or "turbo"
        key = adm.get("execution_profile_id") or f"family:{fam}"
        entry = by_model.setdefault(
            key, {"model_group": key, "family": fam, "waiting": 0, "oldest_age_seconds": 0.0}
        )
        entry["waiting"] += 1
        if created is not None:
            age = (now - as_utc(created)).total_seconds()
            entry["oldest_age_seconds"] = round(max(entry["oldest_age_seconds"], age), 1)
    depths = None
    try:
        from ..queue import build_redis

        r = build_redis(settings.redis_url)
        try:
            depths = {
                "main": int(r.llen("oal:queue:ace-step-1.5")),
                "burst": int(r.llen("oal:queue:ace-step-1.5:burst")),
            }
        finally:
            r.close()
    except Exception:
        depths = None
    return JSONResponse(
        {
            "models": sorted(by_model.values(), key=lambda m: -m["waiting"]),
            "workers": [
                {
                    "id": w.id,
                    "loaded_model": w.loaded_model,
                    "drain": w.drain,
                    "quarantined": w.unhealthy_until is not None and as_utc(w.unhealthy_until) > now,
                    "last_heartbeat": w.last_heartbeat.isoformat() if w.last_heartbeat else None,
                }
                for w in workers
            ],
            "queue_depths": depths,
        }
    )


@router.get("/admin/workers")
def admin_workers(request: Request) -> JSONResponse:
    """All registered workers with derived status."""
    from ..models import Worker
    from ..orchestration import as_utc

    with request.app.state.db.session() as session:
        workers = list(session.execute(select(Worker)).scalars())
    now = utcnow()
    out = []
    for w in workers:
        fresh = w.last_heartbeat is not None and (now - as_utc(w.last_heartbeat)).total_seconds() < 120
        out.append(
            {
                "id": w.id,
                "kind": w.kind,
                "drain": w.drain,
                "status": "draining" if w.drain else "online" if fresh else "stale",
                "gpu_util": w.gpu_util,
                "vram_used_mb": w.vram_used_mb,
                "vram_total_mb": w.vram_total_mb,
                "last_heartbeat": w.last_heartbeat.isoformat() if w.last_heartbeat else None,
            }
        )
    return JSONResponse({"workers": out})


ALLOWED_ENVIRONMENTS = ("production", "staging", "development")


class EnvironmentSetting(BaseModel):
    value: str


@router.put("/admin/settings/environment")
def admin_put_environment(payload: EnvironmentSetting, request: Request) -> JSONResponse:
    if payload.value not in ALLOWED_ENVIRONMENTS:
        raise ApiError(
            422,
            "ENVIRONMENT_UNKNOWN",
            "Unknown environment.",
            {"allowed": list(ALLOWED_ENVIRONMENTS)},
        )
    with request.app.state.db.session() as session:
        row = session.get(SiteSetting, "environment")
        if row is None:
            session.add(SiteSetting(key="environment", value=payload.value))
        else:
            row.value = payload.value
        session.commit()
    return JSONResponse(content={"environment": payload.value})


@router.get("/admin/credits")
def admin_credits(
    request: Request,
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    reason: str | None = Query(default=None, max_length=60),
) -> JSONResponse:
    """Credit ledger with usernames, newest first."""
    from sqlalchemy import func as sa_func

    from ..models import CreditEntry

    with request.app.state.db.session() as session:
        stmt = select(CreditEntry)
        if reason:
            stmt = stmt.where(CreditEntry.reason == reason)
        total = session.execute(select(sa_func.count()).select_from(stmt.subquery())).scalar_one()
        rows = list(
            session.execute(
                select(CreditEntry, User.username)
                .outerjoin(User, User.id == func.replace(CreditEntry.owner_id, "usr_", ""))
                .where(*([CreditEntry.reason == reason] if reason else []))
                .order_by(CreditEntry.created_at.desc())
                .limit(limit)
                .offset(offset)
            ).all()
        )
    return JSONResponse(
        {
            "items": [
                {
                    "id": entry.id,
                    "owner_id": entry.owner_id,
                    "user": username or entry.owner_id.replace("tok_", "api:")[:14],
                    "delta": entry.delta,
                    "reason": entry.reason,
                    "job_id": entry.job_id,
                    "created_at": entry.created_at.isoformat() if entry.created_at else None,
                }
                for entry, username in rows
            ],
            "total": total,
        }
    )


@router.post("/admin/workers/{worker_id}/drain")
def admin_worker_drain(worker_id: str, request: Request) -> JSONResponse:
    """Toggle the drain flag; workers check it before claiming new jobs."""
    from ..models import Worker

    with request.app.state.db.session() as session:
        worker = session.get(Worker, worker_id)
        if worker is None:
            raise ApiError(404, "WORKER_NOT_FOUND", "Worker not found.")
        worker.drain = not worker.drain
        session.commit()
        return JSONResponse({"id": worker.id, "drain": worker.drain})


@router.delete("/admin/workers/stale")
def admin_workers_purge(request: Request) -> JSONResponse:
    """Remove workers whose last heartbeat is older than 24 hours."""
    from datetime import timedelta

    from sqlalchemy import or_

    from ..models import Worker

    cutoff = utcnow() - timedelta(hours=24)
    with request.app.state.db.session() as session:
        rows = list(
            session.execute(
                select(Worker).where(
                    or_(Worker.last_heartbeat.is_(None), Worker.last_heartbeat < cutoff)
                )
            ).scalars()
        )
        for worker in rows:
            session.delete(worker)
        session.commit()
    return JSONResponse({"purged": len(rows)})


@router.get("/admin/jobs/{job_id}")
def admin_job_detail(job_id: str, request: Request) -> JSONResponse:
    """Single job with its full event timeline."""
    from ..models import Job, JobEvent

    with request.app.state.db.session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if job is None:
            raise ApiError(404, "JOB_NOT_FOUND", "Job not found.")
        username = None
        if job.owner_id.startswith("usr_"):
            user = session.get(User, job.owner_id[4:])
            username = user.username if user else None
        events = list(
            session.execute(
                select(JobEvent).where(JobEvent.job_id == job.id).order_by(JobEvent.id)
            ).scalars()
        )
    runtime = None
    if job.started_at and job.finished_at:
        runtime = max(0.0, (job.finished_at - job.started_at).total_seconds())
    return JSONResponse(
        {
            "job_id": job.id,
            "owner_id": job.owner_id,
            "user": username or job.owner_id.replace("tok_", "api:")[:14],
            "operation": job.operation,
            "task": TASK_LABELS.get(job.operation, job.operation),
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            "error_code": job.error_code,
            "error_message": job.error_message,
            "runtime_seconds": runtime,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "events": [
                {
                    "event": ev.event,
                    "status": ev.status,
                    "stage": ev.stage,
                    "created_at": ev.created_at.isoformat() if ev.created_at else None,
                }
                for ev in events
            ],
        }
    )


@router.post("/admin/trainings/{run_id}/cancel")
def admin_training_cancel(run_id: str, request: Request) -> JSONResponse:
    """Cancel a queued/running voice job from the admin console (run_id = job id)."""
    from ..models import Job
    from ..orchestration import append_event

    with request.app.state.db.session() as session:
        job = session.get(Job, run_id)
        if job is None or job.operation not in ("voice.analyze", "voice.train", "voice.validate"):
            raise ApiError(404, "JOB_NOT_FOUND", "Voice training job not found.")
        if job.status == "queued":
            job.status = "cancelled"
            job.cancel_requested_at = utcnow()
            job.finished_at = utcnow()
            append_event(session, job.id, job.status, job.status)
        elif job.status == "running":
            job.status = "cancelling"
            job.cancel_requested_at = utcnow()
            append_event(session, job.id, job.status, job.status)
        elif job.status in ("cancelling", "cancelled"):
            pass
        else:
            raise ApiError(
                409, "STATE_CONFLICT", f"Training run in state '{job.status}' cannot be cancelled."
            )
        session.commit()
        return JSONResponse({"run_id": job.id, "status": job.status})


@router.post("/admin/users/{user_id}/credits")
def admin_user_credits(user_id: str, payload: AdminCreditAdjust, request: Request) -> JSONResponse:
    from ..models import CreditEntry

    with request.app.state.db.session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "User not found.")
        user.credits_balance = max(0, user.credits_balance + payload.delta)
        session.add(
            CreditEntry(
                owner_id="usr_" + user.id,
                delta=payload.delta,
                reason=payload.reason,
                note=payload.note,
            )
        )
        session.commit()
        balance = user.credits_balance
    return JSONResponse({"credits_balance": balance})


@router.get("/admin/users/{user_id}/credits")
def admin_user_ledger(user_id: str, request: Request, limit: int = Query(default=50, ge=1, le=200)) -> JSONResponse:
    from ..models import CreditEntry

    with request.app.state.db.session() as session:
        if session.get(User, user_id) is None:
            raise ApiError(404, "USER_NOT_FOUND", "User not found.")
        rows = list(
            session.execute(
                select(CreditEntry)
                .where(CreditEntry.owner_id == "usr_" + user_id)
                .order_by(CreditEntry.created_at.desc())
                .limit(limit)
            ).scalars()
        )
    return JSONResponse(
        {
            "entries": [
                {
                    "id": e.id,
                    "delta": e.delta,
                    "reason": e.reason,
                    "note": e.note,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in rows
            ]
        }
    )


# --- M14e: admin LoRA training pipeline ---------------------------------------


def _song_title(filename: str) -> str:
    import re

    stem = filename.rsplit(".", 1)[0]
    stem = re.sub(r"^\s*\d+[\s._-]+", "", stem)
    stem = re.sub(r"\s*[\[(].{0,30}[\])]\s*$", "", stem)
    return stem.strip() or filename


@router.post("/admin/loras/upload", status_code=202)
async def admin_lora_upload(
    request: Request,
    user: User = Depends(require_admin),
    name: str = Form(..., max_length=200),
    tags: str = Form(default="", max_length=500),
    files: list = File(...),
) -> JSONResponse:
    """Upload song files (title parsed from filename) into a UAIS training
    library, freeze version 1 and start voice training on Turbo."""
    import hashlib as _hashlib

    from ..models import (
        ArtistProfile,
        Asset,
        Job,
        VoiceAdapter,
        VoiceDataset,
        VoiceDatasetVersion,
        VoiceRecording,
    )
    from ..orchestration import append_event, enqueue
    from ..models import new_uuid, utcnow as _utcnow
    from ..uais.capabilities import capability

    settings = request.app.state.settings
    owner_id = "usr_" + user.id
    tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
    if not files:
        raise ApiError(422, "NO_FILES", "Attach at least one audio file.")
    cap = capability("ace-step-1.5-turbo")

    with request.app.state.db.session() as session:
        profile = ArtistProfile(id=new_uuid(), owner_id=owner_id, name=name, slug=_hashlib.sha1(name.encode()).hexdigest()[:8])
        session.add(profile)
        session.flush()
        dataset = VoiceDataset(id=new_uuid(), artist_profile_id=profile.id, owner_id=owner_id, name=f"{name} library")
        session.add(dataset)
        session.flush()

        titles = []
        manifest = []
        for upload in files:
            body = await upload.read()
            if not body:
                raise ApiError(422, "EMPTY_FILE", f"{upload.filename} is empty.")
            title = _song_title(upload.filename or "untitled")
            titles.append(title)
            key = f"owners/{owner_id}/uploads/lora-{dataset.id}/{new_uuid()}.wav"
            checksum = request.app.state.storage.put(key, body)
            caption = ", ".join(tag_list + [name.lower()])
            asset = Asset(
                id=new_uuid(), owner_id=owner_id, storage_key=key, role="mix_wav", kind="uploaded",
                mime=upload.content_type or "audio/wav", bytes=len(body), sha256=checksum,
                title=title, finalized_at=_utcnow(),
            )
            from ..naming import assign_asset_slug

            assign_asset_slug(session, asset)
            session.add(asset)
            session.flush()
            recording = VoiceRecording(
                id=new_uuid(), dataset_id=dataset.id, artist_profile_id=profile.id, owner_id=owner_id,
                asset_id=asset.id, filename=upload.filename or "untitled", sha256=checksum, bytes=len(body),
                qc_json={"verdict": "usable", "source": "admin-upload",
                         "caption": f"{caption}, {title.lower()}"},
                consent_json={"declaration": "admin-supplied authorized training set",
                              "declared_at": _utcnow().isoformat()},
            )
            session.add(recording)
            manifest.append({"recording_id": recording.id, "asset_id": asset.id, "sha256": checksum,
                             "duration_seconds": None, "caption": recording.qc_json["caption"]})
        session.flush()

        frozen = _hashlib.sha256(
            "\n".join(sorted(f"{m['sha256']}|{m['recording_id']}" for m in manifest)).encode()
        ).hexdigest()
        version = VoiceDatasetVersion(
            id=new_uuid(), dataset_id=dataset.id, owner_id=owner_id, version_number=1, frozen_sha256=frozen,
            manifest_json={"recordings": manifest},
            report_json={"recordings": len(manifest), "source": "admin-upload", "warnings": []},
        )
        session.add(version)
        dataset.latest_version_number = 1

        recipe = settings.train_recipe_revision
        adapter = VoiceAdapter(
            id=new_uuid(), artist_profile_id=profile.id, owner_id=owner_id,
            dataset_version_id=version.id, model_selection="ace-step-1.5-turbo",
            engine_model=cap.engine_model if cap else "acestep-v15-turbo",
            base_revision=cap.base_revision if cap else "",
            training_config_json={"max_epochs": 60}, state="training",
        )
        session.add(adapter)
        job = Job(
            id=new_uuid(), owner_id=owner_id, operation="voice.train",
            model_id=settings.train_queue_model_id, model_revision=recipe, status="queued",
            request_json={
                "profile_id": profile.id, "adapter_id": adapter.id,
                "model_selection": "ace-step-1.5-turbo",
            },
            request_hash=f"admin-lora:{dataset.id}", idempotency_key=new_uuid(),
        )
        session.add(job)
        adapter.training_job_id = job.id
        enqueue(session, job, settings)
        append_event(session, job.id, "queued", "queued")
        session.commit()
        profile_id, dataset_id, job_id, version_id, adapter_id = (
            profile.id, dataset.id, job.id, version.id, adapter.id)
    return JSONResponse(
        status_code=202,
        content={"profile_id": profile_id, "dataset_id": dataset_id, "dataset_version_id": version_id,
                 "adapter_id": adapter_id, "job_id": job_id, "titles": titles},
    )


class AdminLoraPublish(BaseModel):
    adapter_id: str
    name: str = Field(max_length=200)
    tags: str = Field(default="", max_length=500)
    auto_apply: bool = True
    priority: int = 0


@router.post("/admin/loras", status_code=201)
def admin_lora_publish(payload: AdminLoraPublish, request: Request) -> JSONResponse:
    from ..models import Lora, VoiceAdapter, new_uuid

    with request.app.state.db.session() as session:
        adapter = session.get(VoiceAdapter, payload.adapter_id)
        if adapter is None:
            raise ApiError(404, "ADAPTER_NOT_FOUND", "Voice adapter not found.")
        if adapter.state not in ("ready", "validated", "stale"):
            raise ApiError(409, "STATE_CONFLICT",
                           "Only trained adapters can be published.", {"state": adapter.state})
        if not adapter.storage_prefix or not adapter.files_json:
            raise ApiError(409, "NO_ADAPTER", "Adapter has no exported artifact files.")
        if session.execute(select(Lora).where(Lora.name == payload.name)).scalar_one_or_none():
            raise ApiError(409, "NAME_TAKEN", "A style model with this name exists.")
        base_model_id = "ace-step-1.5-xl" if "xl" in adapter.model_selection else "ace-step-1.5"
        lora = Lora(
            id=new_uuid(),
            name=payload.name,
            kind="style",
            tags_json=[t.strip().lower() for t in payload.tags.split(",") if t.strip()],
            storage_prefix=adapter.storage_prefix,
            files_json=list(adapter.files_json),
            base_model_id=base_model_id,
            base_revision=adapter.base_revision,
            auto_apply=payload.auto_apply,
            priority=payload.priority,
            state="active",
            provenance="trained",
            adapter_id=adapter.id,
        )
        session.add(lora)
        session.commit()
        body = {"id": lora.id, "name": lora.name, "tags": lora.tags_json, "auto_apply": lora.auto_apply}
    return JSONResponse(status_code=201, content=body)


class AdminLoraPatch(BaseModel):
    tags: str | None = Field(default=None, max_length=500)
    auto_apply: bool | None = None
    priority: int | None = None
    state: str | None = Field(default=None, pattern=r"^(active|retired)$")
    default_scale: float | None = Field(default=None, ge=0.0, le=2.0)


@router.get("/admin/loras")
def admin_loras(request: Request) -> JSONResponse:
    from ..models import Job, Lora, VoiceAdapter

    with request.app.state.db.session() as session:
        rows = list(session.execute(select(Lora).order_by(Lora.created_at.desc())).scalars())
        out = []
        for l in rows:
            run_status = None
            if l.adapter_id:
                adapter = session.get(VoiceAdapter, l.adapter_id)
                if adapter is not None and adapter.training_job_id:
                    job = session.get(Job, adapter.training_job_id)
                    run_status = job.status if job else None
            out.append(
                {
                    "id": l.id, "name": l.name, "kind": l.kind, "tags": l.tags_json,
                    "state": l.state, "auto_apply": l.auto_apply, "priority": l.priority,
                    "default_scale": l.default_scale, "provenance": l.provenance,
                    "adapter_id": l.adapter_id, "training_status": run_status,
                }
            )
    return JSONResponse({"loras": out})


@router.patch("/admin/loras/{lora_id}")
def admin_lora_patch(lora_id: str, payload: AdminLoraPatch, request: Request) -> JSONResponse:
    from ..models import Lora

    with request.app.state.db.session() as session:
        lora = session.get(Lora, lora_id)
        if lora is None:
            raise ApiError(404, "LORA_NOT_FOUND", "Style model not found.")
        if payload.tags is not None:
            lora.tags_json = [t.strip().lower() for t in payload.tags.split(",") if t.strip()]
        if payload.auto_apply is not None:
            lora.auto_apply = payload.auto_apply
        if payload.priority is not None:
            lora.priority = payload.priority
        if payload.state is not None:
            lora.state = payload.state
        if payload.default_scale is not None:
            lora.default_scale = payload.default_scale
        session.commit()
    return JSONResponse({"id": lora.id, "state": lora.state, "tags": lora.tags_json, "auto_apply": lora.auto_apply})


@router.delete("/admin/loras/{lora_id}", status_code=204)
def admin_lora_delete(lora_id: str, request: Request) -> JSONResponse:
    from ..models import Lora

    with request.app.state.db.session() as session:
        lora = session.get(Lora, lora_id)
        if lora is None:
            raise ApiError(404, "LORA_NOT_FOUND", "Style model not found.")
        session.delete(lora)
        session.commit()
    return JSONResponse(status_code=204, content=None)


class VastActionRequest(BaseModel):
    action: str = Field(pattern=r"^(start|stop|destroy)$")


def _vast_request(request: Request, method: str, path: str, json_body: dict | None = None):
    import httpx

    settings = request.app.state.settings
    if not settings.vast_api_key:
        raise ApiError(503, "VAST_NOT_CONFIGURED", "OAL_VAST_API_KEY is not set.")
    resp = httpx.request(
        method,
        f"{settings.vast_api_url.rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {settings.vast_api_key}"},
        json=json_body,
        timeout=15.0,
    )
    if resp.status_code >= 400:
        raise ApiError(502, "VAST_API_ERROR", f"Vast API error {resp.status_code}: {resp.text[:200]}")
    return resp.json()


@router.get("/admin/vast/instances")
def admin_vast_instances(request: Request) -> JSONResponse:
    """Recently used Vast nodes (registry) merged with live Vast status."""
    from ..models import VastInstance

    live: dict[str, str] = {}
    live_ok = False
    try:
        rows = _vast_request(request, "GET", "/instances/")
        rows = rows.get("instances", []) if isinstance(rows, dict) else rows
        for row in rows if isinstance(rows, list) else []:
            live[str(row.get("id"))] = str(row.get("actual_status", ""))
        live_ok = True
    except ApiError:
        pass
    with request.app.state.db.session() as session:
        records = list(session.execute(select(VastInstance)).scalars())
    out = []
    for rec in records:
        out.append(
            {
                "id": rec.id,
                "vast_instance_id": rec.vast_instance_id,
                "role": rec.role,
                "gpu_model": rec.gpu_model,
                "state": rec.state,
                "live_status": live.get(rec.vast_instance_id),
                "last_used_at": rec.last_used_at.isoformat() if rec.last_used_at else None,
                "stopped_at": rec.stopped_at.isoformat() if rec.stopped_at else None,
            }
        )
    return JSONResponse({"instances": out, "live_available": live_ok})


@router.post("/admin/vast/instances/{vast_instance_id}/action")
def admin_vast_instance_action(
    vast_instance_id: str,
    payload: VastActionRequest,
    request: Request,
) -> JSONResponse:
    from ..models import VastInstance

    _vast_request(
        request, "POST", f"/instances/{vast_instance_id}/action/",
        {"action_type": payload.action},
    )
    with request.app.state.db.session() as session:
        rec = session.execute(
            select(VastInstance).where(VastInstance.vast_instance_id == vast_instance_id)
        ).scalar_one_or_none()
        if rec is not None:
            if payload.action == "destroy":
                session.delete(rec)
            else:
                rec.state = "running" if payload.action == "start" else "stopped"
                if payload.action == "stop":
                    rec.stopped_at = utcnow()
            session.commit()
    return JSONResponse({"ok": True, "action": payload.action})


# --- M17: user delete, error logs, pricing -----------------------------------


@router.delete("/admin/users/{user_id}", status_code=204)
def admin_delete_user(user_id: str, request: Request) -> JSONResponse:
    """Soft-delete a user (purged after 30 days by the autoscaler)."""
    with request.app.state.db.session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "User not found.")
        user.deleted_at = utcnow()
        user.state = "disabled"
        session.commit()
    return JSONResponse(status_code=204, content=None)


class AdminErrorPatch(BaseModel):
    resolved: bool


@router.get("/admin/errors")
def admin_errors(
    request: Request,
    limit: int = Query(default=10, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    component: str | None = Query(default=None, max_length=40),
    resolved: bool | None = Query(default=None),
) -> JSONResponse:
    from ..models import ErrorLog

    with request.app.state.db.session() as session:
        stmt = select(ErrorLog)
        if component:
            stmt = stmt.where(ErrorLog.component == component)
        if resolved is not None:
            stmt = stmt.where(ErrorLog.resolved.is_(resolved))
        total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = list(
            session.execute(
                select(ErrorLog).where(
                    *( [ErrorLog.component == component] if component else [] ),
                    *( [ErrorLog.resolved.is_(resolved)] if resolved is not None else [] ),
                )
                .order_by(ErrorLog.id.desc())
                .limit(limit)
                .offset(offset)
            ).scalars()
        )
    return JSONResponse(
        {
            "items": [
                {
                    "id": e.id,
                    "component": e.component,
                    "route": e.route,
                    "http_status": e.http_status,
                    "error_code": e.error_code,
                    "message": e.message[:300],
                    "job_id": e.job_id,
                    "worker_id": e.worker_id,
                    "resolved": e.resolved,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e in rows
            ],
            "total": total,
        }
    )


@router.get("/admin/errors/{error_id}")
def admin_error_detail(error_id: int, request: Request) -> JSONResponse:
    from ..errorlog import agent_brief
    from ..models import ErrorLog

    with request.app.state.db.session() as session:
        e = session.get(ErrorLog, error_id)
        if e is None:
            raise ApiError(404, "ERROR_NOT_FOUND", "Error log not found.")
        return JSONResponse(
            {
                "id": e.id,
                "component": e.component,
                "route": e.route,
                "http_status": e.http_status,
                "error_code": e.error_code,
                "message": e.message,
                "traceback": e.traceback,
                "context_json": e.context_json or {},
                "job_id": e.job_id,
                "worker_id": e.worker_id,
                "user_id": e.user_id,
                "fingerprint": e.fingerprint,
                "resolved": e.resolved,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "agent_brief": agent_brief(e),
            }
        )


@router.patch("/admin/errors/{error_id}")
def admin_patch_error(error_id: int, payload: AdminErrorPatch, request: Request) -> JSONResponse:
    from ..models import ErrorLog

    with request.app.state.db.session() as session:
        e = session.get(ErrorLog, error_id)
        if e is None:
            raise ApiError(404, "ERROR_NOT_FOUND", "Error log not found.")
        e.resolved = payload.resolved
        e.resolved_at = utcnow() if payload.resolved else None
        session.commit()
    return JSONResponse({"ok": True, "resolved": payload.resolved})


class AdminPricingItem(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    kind: str = Field(pattern=r"^(plan|pack)$")
    name: str = Field(default="", max_length=120)
    price_usd: int = Field(default=0, ge=0)
    credits: int = Field(default=0, ge=0)
    position: int = Field(default=0)
    visible: bool = True


class AdminPricingUpdate(BaseModel):
    items: list[AdminPricingItem]


@router.get("/admin/pricing")
def admin_get_pricing(request: Request) -> JSONResponse:
    from .billing import load_pricing

    with request.app.state.db.session() as session:
        return JSONResponse(load_pricing(session))


class AdminAbusePatch(BaseModel):
    status: str = Field(pattern=r"^(open|reviewing|resolved|rejected)$")
    decision: str | None = Field(default=None, max_length=200)
    appeal_status: str | None = Field(default=None, max_length=40)


@router.put("/admin/pricing")
def admin_put_pricing(
    payload: AdminPricingUpdate,
    request: Request,
    admin: User = Depends(require_admin),
) -> JSONResponse:
    from ..audit import record_admin_audit
    from ..models import Pricing
    from .billing import load_pricing

    with request.app.state.db.session() as session:
        for item in payload.items:
            row = session.get(Pricing, item.id)
            if row is None:
                row = Pricing(id=item.id)
                session.add(row)
            row.kind = item.kind
            row.name = item.name or row.name or item.id
            row.price_usd = item.price_usd
            row.credits = item.credits
            row.position = item.position
            row.visible = item.visible
        record_admin_audit(session, admin.id, "pricing.update", "pricing", None, context_json={"items": len(payload.items)})
        session.commit()
        return JSONResponse(load_pricing(session))


@router.get("/admin/guests")
def admin_list_guests(
    request: Request,
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    from datetime import date

    from ..models import GuestQuotaCounter, GuestSession, Job

    today = utcnow().date()
    with request.app.state.db.session() as session:
        stmt = select(GuestSession)
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where(or_(GuestSession.id.like(like), GuestSession.claimed_user_id.like(like)))
        total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        rows = list(session.execute(stmt.order_by(GuestSession.created_at.desc()).limit(limit).offset(offset)).scalars())
        guest_ids = [g.id for g in rows]
        counters = {}
        jobs = {}
        if guest_ids:
            for gid, used in session.execute(
                select(GuestQuotaCounter.guest_id, GuestQuotaCounter.used).where(
                    GuestQuotaCounter.guest_id.in_(guest_ids), GuestQuotaCounter.day == today
                )
            ).all():
                counters[gid] = int(used)
            for gid, cnt in session.execute(
                select(func.replace(Job.owner_id, "g_", ""), func.count())
                .where(Job.owner_id.in_([f"g_{gid}" for gid in guest_ids]))
                .group_by(Job.owner_id)
            ).all():
                jobs[gid] = int(cnt)
        users = {}
        claimed_ids = [g.claimed_user_id for g in rows if g.claimed_user_id]
        if claimed_ids:
            for uid, username in session.execute(select(User.id, User.username).where(User.id.in_(claimed_ids))).all():
                users[uid] = username
    return JSONResponse(
        {
            "guests": [
                {
                    "id": g.id,
                    "created_at": g.created_at.isoformat() if g.created_at else None,
                    "expires_at": g.expires_at.isoformat() if g.expires_at else None,
                    "policy_accepted": g.policy_accepted_at is not None,
                    "policy_version": g.policy_version,
                    "marketing_consent": g.marketing_consent,
                    "claimed_user_id": g.claimed_user_id,
                    "claimed_username": users.get(g.claimed_user_id),
                    "jobs_count": jobs.get(g.id, 0),
                    "quota_used_today": counters.get(g.id, 0),
                    "quota_limit": request.app.state.settings.guest_daily_song_limit,
                }
                for g in rows
            ],
            "total": total,
            "date": today.isoformat(),
        }
    )


@router.get("/admin/policies")
def admin_policies(request: Request) -> JSONResponse:
    from ..models import PolicyAcceptance
    from ..policies import current_policy_payload

    with request.app.state.db.session() as session:
        payload = current_policy_payload(session, request.app.state.settings)
        acceptances = list(
            session.execute(
                select(PolicyAcceptance).order_by(PolicyAcceptance.accepted_at.desc()).limit(50)
            ).scalars()
        )
    return JSONResponse(
        {
            **payload,
            "acceptances": [
                {
                    "subject_type": a.subject_type,
                    "subject_id": a.subject_id,
                    "policy_version": a.policy_version,
                    "marketing_consent": a.marketing_consent,
                    "accepted_at": a.accepted_at.isoformat() if a.accepted_at else None,
                }
                for a in acceptances
            ],
        }
    )


@router.get("/admin/audits")
def admin_audits(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    from ..models import AdminAudit

    with request.app.state.db.session() as session:
        rows = list(session.execute(select(AdminAudit).order_by(AdminAudit.created_at.desc()).limit(limit).offset(offset)).scalars())
    return JSONResponse(
        {
            "audits": [
                {
                    "id": a.id,
                    "admin_id": a.admin_id,
                    "action": a.action,
                    "target_type": a.target_type,
                    "target_id": a.target_id,
                    "reason": a.reason,
                    "context_json": a.context_json,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in rows
            ]
        }
    )


@router.get("/admin/abuse-reports")
def admin_abuse_reports(
    request: Request,
    status: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    from ..models import AbuseReport

    with request.app.state.db.session() as session:
        stmt = select(AbuseReport)
        if status:
            stmt = stmt.where(AbuseReport.status == status)
        rows = list(session.execute(stmt.order_by(AbuseReport.created_at.desc()).limit(limit).offset(offset)).scalars())
    return JSONResponse(
        {
            "reports": [
                {
                    "id": r.id,
                    "reporter_owner_id": r.reporter_owner_id,
                    "subject_type": r.subject_type,
                    "subject_id": r.subject_id,
                    "reason": r.reason,
                    "details": r.details,
                    "status": r.status,
                    "decision": r.decision,
                    "appeal_status": r.appeal_status,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]
        }
    )


@router.patch("/admin/abuse-reports/{report_id}")
def admin_patch_abuse_report(
    report_id: str,
    payload: AdminAbusePatch,
    request: Request,
    admin: User = Depends(require_admin),
) -> JSONResponse:
    from ..audit import record_admin_audit
    from ..models import AbuseReport

    with request.app.state.db.session() as session:
        report = session.get(AbuseReport, report_id)
        if report is None:
            raise ApiError(404, "REPORT_NOT_FOUND", "Abuse report not found.")
        report.status = payload.status
        if payload.decision is not None:
            report.decision = payload.decision
        if payload.appeal_status is not None:
            report.appeal_status = payload.appeal_status
        report.decided_by = admin.id
        report.decided_at = utcnow()
        report.updated_at = utcnow()
        record_admin_audit(session, admin.id, "abuse.update", "abuse_report", report.id, reason=payload.status)
        session.commit()
    return JSONResponse({"id": report.id, "status": report.status, "decision": report.decision})


# --- M18: admin media catalog (browse + listen + moderate all owners) --------

_ASSET_STATUS_FILTERS = ("all", "live", "shared", "trashed", "expired", "purged", "uploads", "stems")


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _enrich_asset_rows(session, assets, now):
    from ..models import Job

    owner_ids = sorted({a.owner_id for a in assets})
    names: dict[str, str] = {}
    user_ids = sorted({o[4:] for o in owner_ids if o.startswith("usr_")})
    if user_ids:
        for u in session.execute(select(User).where(User.id.in_(user_ids))).scalars():
            names["usr_" + u.id] = u.username
    job_ids = [a.job_id for a in assets if a.job_id]
    jobs: dict[str, tuple[str | None, object]] = {}
    if job_ids:
        for jid, model_id, rjson in session.execute(
            select(Job.id, Job.model_id, Job.request_json).where(Job.id.in_(job_ids))
        ).all():
            jobs[jid] = (model_id, (rjson or {}).get("seed"))
    rows = []
    for asset in assets:
        model_id, seed = jobs.get(asset.job_id, (None, None)) if asset.job_id else (None, None)
        state = _asset_state(asset, now)
        rows.append(
            {
                "asset_id": asset.id,
                "owner_id": asset.owner_id,
                "user": names.get(asset.owner_id, asset.owner_id.replace("tok_", "api:")[:14]),
                "role": asset.role,
                "kind": asset.kind,
                "mime": asset.mime,
                "bytes": asset.bytes,
                "duration_seconds": asset.duration_seconds,
                "title": asset.title,
                "slug": asset.slug,
                "shared": bool(asset.shared),
                "workspace_id": asset.workspace_id,
                "job_id": asset.job_id,
                "model_id": model_id,
                "seed": seed,
                "state": state,
                "byte_present": asset.purged_at is None,
                "playable": asset.mime.startswith("audio/") and asset.purged_at is None,
                "content_url": f"/api/v1/admin/artifacts/{asset.id}/content",
                "waveform_url": (
                    f"/api/v1/admin/artifacts/{asset.id}/waveform" if asset.storage_key.endswith(".wav") else None
                ),
                "download_name": _safe_filename(asset.slug or asset.title, asset.id) + _filename_ext(asset),
                "created_at": _iso(asset.created_at),
                "finalized_at": _iso(asset.finalized_at),
                "expires_at": _iso(asset.expires_at),
                "deleted_at": _iso(asset.deleted_at),
                "purge_after": _iso(asset.purge_after),
                "purged_at": _iso(asset.purged_at),
            }
        )
    return rows


@router.get("/admin/assets")
def admin_assets(
    request: Request,
    user_id: str | None = Query(default=None, max_length=36),
    owner_id: str | None = Query(default=None, max_length=80),
    q: str | None = Query(default=None, max_length=120),
    role: str | None = Query(default=None, max_length=40),
    kind: str | None = Query(default=None, max_length=20),
    status: str = Query(default="all", max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    """Cross-owner media catalog for admins: browse + listen, incl. expired/trashed/purged."""
    from ..models import Asset

    if status not in _ASSET_STATUS_FILTERS:
        raise ApiError(422, "INVALID_STATUS", f"status must be one of {list(_ASSET_STATUS_FILTERS)}")

    now = utcnow()
    with request.app.state.db.session() as session:
        stmt = select(Asset)
        if owner_id:
            stmt = stmt.where(Asset.owner_id == owner_id)
        elif user_id:
            stmt = stmt.where(Asset.owner_id == "usr_" + user_id)
        if role:
            stmt = stmt.where(Asset.role == role)
        if kind:
            stmt = stmt.where(Asset.kind == kind)

        if status == "live":
            stmt = stmt.where(Asset.deleted_at.is_(None), Asset.purged_at.is_(None)).where(
                or_(Asset.expires_at.is_(None), Asset.expires_at > now)
            )
        elif status == "shared":
            stmt = stmt.where(Asset.deleted_at.is_(None), Asset.purged_at.is_(None), Asset.shared.is_(True))
        elif status == "trashed":
            stmt = stmt.where(Asset.deleted_at.is_not(None), Asset.purged_at.is_(None))
        elif status == "expired":
            stmt = stmt.where(Asset.purged_at.is_(None), Asset.expires_at.is_not(None), Asset.expires_at <= now)
        elif status == "purged":
            stmt = stmt.where(Asset.purged_at.is_not(None))
        elif status == "uploads":
            stmt = stmt.where(Asset.kind == "uploaded")
        elif status == "stems":
            stmt = stmt.where(Asset.role.in_(("stems_wav", "stems_zip")), Asset.deleted_at.is_(None))

        if q:
            like = f"%{q.strip()}%"
            conds = [Asset.title.ilike(like), Asset.storage_key.ilike(like), Asset.id == q.strip()]
            owner_candidates = [
                "usr_" + uid
                for (uid,) in session.execute(
                    select(User.id).where(or_(User.username.ilike(like), User.email.ilike(like)))
                ).all()
            ]
            if owner_candidates:
                conds.append(Asset.owner_id.in_(owner_candidates))
            stmt = stmt.where(or_(*conds))

        total = session.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
        assets = list(session.execute(stmt.order_by(Asset.created_at.desc()).limit(limit).offset(offset)).scalars())
        items = _enrich_asset_rows(session, assets, now)
    return JSONResponse({"items": items, "total": total})


@router.get("/admin/artifacts/{asset_id}/content")
def admin_artifact_content(
    asset_id: str,
    request: Request,
    download: bool = Query(default=False),
) -> Response:
    """Forensic playback/download stream. Admin-gated; serves expired and trashed bytes."""
    from ..models import Asset
    from ..storage import parse_range

    with request.app.state.db.session() as session:
        asset = session.execute(select(Asset).where(Asset.id == asset_id)).scalar_one_or_none()
        if asset is None:
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
        storage_key = asset.storage_key
        mime = asset.mime
        total_bytes = asset.bytes
        purged = asset.purged_at is not None
        disposition = _disposition(asset) if download else None
    if purged:
        raise ApiError(410, "CONTENT_PURGED", "Asset bytes have been purged.")
    byte_range = parse_range(request.headers.get("Range"), total_bytes)
    try:
        stored = request.app.state.storage.get(storage_key, byte_range)
    except FileNotFoundError:
        raise ApiError(404, "CONTENT_MISSING", "Stored file is missing.")
    headers = {"Accept-Ranges": "bytes"}
    if disposition is not None:
        headers["Content-Disposition"] = disposition
    status_code = 200
    if stored.content_range is not None:
        headers["Content-Range"] = stored.content_range
        status_code = 206
    return Response(content=stored.body, status_code=status_code, media_type=mime, headers=headers)


@router.get("/admin/artifacts/{asset_id}/waveform")
def admin_artifact_waveform(asset_id: str, request: Request) -> Response:
    """Cached (or lazily computed) waveform peaks for any asset, incl. expired/trashed."""
    from ..models import Asset

    storage = request.app.state.storage
    with request.app.state.db.session() as session:
        asset = session.execute(select(Asset).where(Asset.id == asset_id)).scalar_one_or_none()
    if asset is None:
        raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
    if not asset.storage_key.endswith(".wav"):
        raise ApiError(404, "WAVEFORM_NOT_FOUND", "No waveform for this asset.")
    key = asset.storage_key[: -len(".wav")] + ".json"
    try:
        stored = storage.get(key)
        return Response(content=stored.body, media_type="application/json")
    except FileNotFoundError:
        pass
    if asset.purged_at is not None:
        raise ApiError(410, "CONTENT_PURGED", "Asset bytes have been purged.")
    try:
        wav = storage.get(asset.storage_key)
    except FileNotFoundError:
        raise ApiError(404, "WAVEFORM_NOT_FOUND", "Audio file is missing.")
    from ..peaks import peaks_json

    body = peaks_json(wav.body)
    try:
        storage.put(key, body)
    except OSError:
        pass
    return Response(content=body, media_type="application/json")


@router.patch("/admin/assets/{asset_id}")
def admin_patch_asset(
    asset_id: str,
    payload: AdminAssetPatch,
    request: Request,
    admin: User = Depends(require_admin),
) -> JSONResponse:
    """Moderation: unshare/re-share a track, or move to Trash / restore it."""
    from ..audit import record_admin_audit
    from ..models import Asset

    now = utcnow()
    with request.app.state.db.session() as session:
        asset = session.get(Asset, asset_id)
        if asset is None:
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
        if payload.shared is not None:
            asset.shared = payload.shared
        if payload.trash is True:
            asset.deleted_at = now
            asset.purge_after = now + timedelta(hours=TRASH_PURGE_HOURS)
        elif payload.trash is False:
            asset.deleted_at = None
            asset.purge_after = None
        record_admin_audit(
            session,
            admin.id,
            "asset.patch",
            "asset",
            asset.id,
            context_json=payload.model_dump(exclude_none=True),
        )
        session.commit()
    return JSONResponse(
        {
            "asset_id": asset.id,
            "shared": bool(asset.shared),
            "deleted_at": _iso(asset.deleted_at),
            "purge_after": _iso(asset.purge_after),
        }
    )


@router.post("/admin/assets/{asset_id}/purge")
def admin_purge_asset(
    asset_id: str,
    request: Request,
    admin: User = Depends(require_admin),
) -> JSONResponse:
    """Irreversibly delete one asset's bytes now (metadata row is kept for audit)."""
    from ..audit import record_admin_audit
    from ..models import Asset
    from ..storage import delete_asset_blobs

    now = utcnow()
    with request.app.state.db.session() as session:
        asset = session.get(Asset, asset_id)
        if asset is None:
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
        already = asset.purged_at is not None
        if not already:
            try:
                delete_asset_blobs(request.app.state.storage, asset.storage_key)
            except OSError as exc:
                raise ApiError(500, "PURGE_FAILED", f"Could not delete stored bytes: {exc}")
            asset.purged_at = now
            if asset.deleted_at is None:
                asset.deleted_at = now
        record_admin_audit(session, admin.id, "asset.purge", "asset", asset.id)
        session.commit()
    return JSONResponse({"asset_id": asset_id, "purged": True, "already_purged": already})


@router.post("/admin/users/{user_id}/purge-content")
def admin_purge_user_content(
    user_id: str,
    request: Request,
    admin: User = Depends(require_admin),
) -> JSONResponse:
    """Irreversibly delete ALL of a user's stored media (account + rows are kept)."""
    from ..audit import record_admin_audit
    from ..models import Asset
    from ..storage import delete_asset_blobs

    owner_id = "usr_" + user_id
    now = utcnow()
    purged = 0
    failed = 0
    with request.app.state.db.session() as session:
        if session.get(User, user_id) is None:
            raise ApiError(404, "USER_NOT_FOUND", "User not found.")
        assets = list(
            session.execute(select(Asset).where(Asset.owner_id == owner_id, Asset.purged_at.is_(None))).scalars()
        )
        for asset in assets:
            try:
                delete_asset_blobs(request.app.state.storage, asset.storage_key)
            except OSError:
                # Cross-host ownership may block unlink; leave the row un-purged.
                failed += 1
                continue
            asset.purged_at = now
            if asset.deleted_at is None:
                asset.deleted_at = now
            purged += 1
        record_admin_audit(
            session,
            admin.id,
            "user.purge-content",
            "user",
            user_id,
            context_json={"assets_purged": purged, "assets_failed": failed},
        )
        session.commit()
    return JSONResponse({"user_id": user_id, "owner_id": owner_id, "assets_purged": purged, "assets_failed": failed})


@router.get("/admin/users/{user_id}/assets")
def admin_user_assets(
    user_id: str,
    request: Request,
    status: str = Query(default="all", max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JSONResponse:
    """A single user's media catalog (same rows as /admin/assets, scoped to the owner)."""
    response = admin_assets(
        request, user_id=user_id, owner_id=None, q=None, role=None, kind=None, status=status, limit=limit, offset=offset
    )
    return response


@router.get("/admin/users/{user_id}")
def admin_user_detail(
    user_id: str,
    request: Request,
    asset_limit: int = Query(default=20, ge=1, le=200),
) -> JSONResponse:
    """Per-user drill-down: account summary + content counts + recent playable generations."""
    from ..models import Asset, Job

    now = utcnow()
    owner_id = "usr_" + user_id
    with request.app.state.db.session() as session:
        user = session.get(User, user_id)
        if user is None:
            raise ApiError(404, "USER_NOT_FOUND", "User not found.")
        payload = user_payload(user)
        created_at = _iso(user.created_at)
        jobs_total = session.execute(
            select(func.count()).select_from(Job).where(Job.owner_id == owner_id)
        ).scalar_one()
        jobs_succeeded = session.execute(
            select(func.count()).select_from(Job).where(Job.owner_id == owner_id, Job.status == "succeeded")
        ).scalar_one()
        jobs_failed = session.execute(
            select(func.count()).select_from(Job).where(Job.owner_id == owner_id, Job.status == "failed")
        ).scalar_one()
        assets_total = session.execute(
            select(func.count()).select_from(Asset).where(Asset.owner_id == owner_id)
        ).scalar_one()
        assets_purged = session.execute(
            select(func.count()).select_from(Asset).where(Asset.owner_id == owner_id, Asset.purged_at.is_not(None))
        ).scalar_one()
        assets_trashed = session.execute(
            select(func.count())
            .select_from(Asset)
            .where(Asset.owner_id == owner_id, Asset.deleted_at.is_not(None), Asset.purged_at.is_(None))
        ).scalar_one()
        assets_shared = session.execute(
            select(func.count())
            .select_from(Asset)
            .where(Asset.owner_id == owner_id, Asset.shared.is_(True), Asset.deleted_at.is_(None))
        ).scalar_one()
        storage_bytes = session.execute(
            select(func.coalesce(func.sum(Asset.bytes), 0)).where(
                Asset.owner_id == owner_id, Asset.purged_at.is_(None)
            )
        ).scalar_one()
        recent = list(
            session.execute(
                select(Asset)
                .where(Asset.owner_id == owner_id)
                .order_by(Asset.created_at.desc())
                .limit(asset_limit)
            ).scalars()
        )
        recent_assets = _enrich_asset_rows(session, recent, now)
    return JSONResponse(
        {
            "user": {**payload, "created_at": created_at},
            "counts": {
                "jobs_total": int(jobs_total),
                "jobs_succeeded": int(jobs_succeeded),
                "jobs_failed": int(jobs_failed),
                "assets_total": int(assets_total),
                "assets_trashed": int(assets_trashed),
                "assets_purged": int(assets_purged),
                "assets_shared": int(assets_shared),
                "storage_bytes": int(storage_bytes),
            },
            "recent_assets": recent_assets,
        }
    )
