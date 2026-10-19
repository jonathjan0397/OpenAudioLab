"""Server-side guest quota helpers."""

from __future__ import annotations

from datetime import date

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings
from .errors import ApiError
from .models import (
    GuestQuotaCounter,
    GuestQuotaReservation,
    GuestSession,
    Job,
    utcnow,
)

GENERATION_OPERATIONS = {
    "music.generate",
    "music.variation",
    "music.extend",
    "music.replace_section",
    "music.remix",
}


def is_guest_owner(owner_id: str | None) -> bool:
    return bool(owner_id and owner_id.startswith("g_"))


def guest_id_from_owner(owner_id: str) -> str:
    return owner_id[2:]


def requested_takes(payload_controls: dict | None) -> int:
    try:
        return max(1, min(4, int((payload_controls or {}).get("variations") or 1)))
    except (TypeError, ValueError):
        return 1


def _ensure_counter(session: Session, guest_id: str, day: date, limit: int) -> GuestQuotaCounter:
    counter = session.execute(
        select(GuestQuotaCounter).where(GuestQuotaCounter.guest_id == guest_id, GuestQuotaCounter.day == day)
    ).scalar_one_or_none()
    if counter is not None:
        return counter
    try:
        with session.begin_nested():
            counter = GuestQuotaCounter(guest_id=guest_id, day=day, used=0, limit=limit)
            session.add(counter)
            session.flush()
    except IntegrityError:
        counter = session.execute(
            select(GuestQuotaCounter).where(GuestQuotaCounter.guest_id == guest_id, GuestQuotaCounter.day == day)
        ).scalar_one()
    return counter


def reserve_guest_quota(
    session: Session,
    guest_id: str,
    job_id: str,
    takes: int,
    settings: Settings,
) -> GuestQuotaReservation:
    day = utcnow().date()
    reservation = session.execute(
        select(GuestQuotaReservation).where(
            GuestQuotaReservation.guest_id == guest_id,
            GuestQuotaReservation.job_id == job_id,
        )
    ).scalar_one_or_none()
    if reservation is not None and reservation.status == "reserved":
        return reservation

    _ensure_counter(session, guest_id, day, settings.guest_daily_song_limit)
    result = session.execute(
        update(GuestQuotaCounter)
        .where(
            GuestQuotaCounter.guest_id == guest_id,
            GuestQuotaCounter.day == day,
            GuestQuotaCounter.used + takes <= GuestQuotaCounter.limit,
        )
        .values(used=GuestQuotaCounter.used + takes, updated_at=utcnow())
    )
    if result.rowcount == 0:
        raise ApiError(
            429,
            "GUEST_QUOTA_EXCEEDED",
            "Guest daily song limit reached.",
            {"limit": settings.guest_daily_song_limit, "requested_takes": takes},
        )

    if reservation is None:
        reservation = GuestQuotaReservation(
            guest_id=guest_id,
            job_id=job_id,
            day=day,
            takes=takes,
            status="reserved",
        )
        session.add(reservation)
    else:
        reservation.day = day
        reservation.takes = takes
        reservation.status = "reserved"
        reservation.reason = None
        reservation.released_at = None
    session.flush()
    return reservation


def _reservation_for_job(session: Session, job_id: str) -> GuestQuotaReservation | None:
    return session.execute(
        select(GuestQuotaReservation).where(GuestQuotaReservation.job_id == job_id)
    ).scalar_one_or_none()


def commit_guest_reservation(session: Session, job: Job) -> None:
    if not is_guest_owner(job.owner_id) or job.operation not in GENERATION_OPERATIONS:
        return
    reservation = _reservation_for_job(session, job.id)
    if reservation is not None and reservation.status == "reserved":
        reservation.status = "committed"
        reservation.updated_at = utcnow()


def release_guest_reservation(session: Session, job: Job, reason: str) -> None:
    if not is_guest_owner(job.owner_id) or job.operation not in GENERATION_OPERATIONS:
        return
    reservation = _reservation_for_job(session, job.id)
    if reservation is None or reservation.status != "reserved":
        return
    reservation.status = "released"
    reservation.reason = reason
    reservation.released_at = utcnow()
    reservation.updated_at = utcnow()
    session.execute(
        update(GuestQuotaCounter)
        .where(
            GuestQuotaCounter.guest_id == reservation.guest_id,
            GuestQuotaCounter.day == reservation.day,
        )
        .values(used=GuestQuotaCounter.used - reservation.takes, updated_at=utcnow())
    )


def guest_allowance(session: Session, guest: GuestSession, settings: Settings) -> dict:
    day = utcnow().date()
    counter = session.execute(
        select(GuestQuotaCounter).where(
            GuestQuotaCounter.guest_id == guest.id,
            GuestQuotaCounter.day == day,
        )
    ).scalar_one_or_none()
    used = int(counter.used) if counter is not None else 0
    limit = settings.guest_daily_song_limit
    return {
        "guest_id": guest.id,
        "date": day.isoformat(),
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "reset_at": _next_utc_midnight(),
        "policy_accepted": guest.policy_accepted_at is not None,
        "policy_version": guest.policy_version,
        "max_duration_seconds": settings.guest_max_duration_seconds,
        "claimed": guest.claimed_user_id is not None,
    }


def _next_utc_midnight() -> str:
    from datetime import timedelta

    now = utcnow()
    tomorrow = (now + timedelta(days=1)).date()
    return f"{tomorrow.isoformat()}T00:00:00+00:00"
