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
        "training": "artist.train",
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
    "artist.train": "Artist Training",
    "artist.evaluate": "Evaluation",
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
    """Recent training runs with live progress, for the admin overview."""
    from ..models import ArtistProfile, ArtistProfileVersion, Job, TrainingRun

    with request.app.state.db.session() as session:
        rows = list(
            session.execute(
                select(
                    TrainingRun, Job.status, Job.progress, Job.stage, Job.created_at, Job.started_at,
                    Job.finished_at, ArtistProfile.name, User.username,
                )
                .join(Job, Job.id == TrainingRun.job_id)
                .outerjoin(ArtistProfileVersion, ArtistProfileVersion.id == TrainingRun.profile_version_id)
                .outerjoin(ArtistProfile, ArtistProfile.id == ArtistProfileVersion.profile_id)
                .outerjoin(User, User.id == func.replace(Job.owner_id, "usr_", ""))
                .order_by(Job.created_at.desc())
                .limit(limit)
            ).all()
        )
    out = []
    for run, status, progress, stage, created, started, finished, name, username in rows:
        eta = None
        if status == "running" and progress and started:
            elapsed = (utcnow() - started).total_seconds()
            eta = round(elapsed * (1 - progress) / progress)
        out.append(
            {
                "run_id": run.id,
                "profile": name or "unnamed",
                "user": username or "—",
                "status": status,
                "stage": stage,
                "progress": progress,
                "eta_seconds": eta,
                "created_at": created.isoformat() if created else None,
                "hardware": run.hardware,
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
        ("Artist Trainer", "Custom Model Training", "artist.train", "v0.9", 99.5),
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

    from ..models import CreditEntry

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
            "custom_training_pct": pct("artist.train"),
            "export_pct": pct("audio.export"),
            "job_counts": op_counts,
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
    """Cancel a queued/running training run from the admin console."""
    from ..models import Job, TrainingRun
    from ..orchestration import append_event

    with request.app.state.db.session() as session:
        run = session.get(TrainingRun, run_id)
        if run is None:
            raise ApiError(404, "RUN_NOT_FOUND", "Training run not found.")
        job = session.execute(select(Job).where(Job.id == run.job_id)).scalar_one_or_none()
        if job is None:
            raise ApiError(404, "JOB_NOT_FOUND", "Training job not found.")
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
        return JSONResponse({"run_id": run.id, "status": job.status})
