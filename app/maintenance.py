"""Retention maintenance: seven-day output expiry and object deletion.

Active artist-profile artifacts and explicitly retained training datasets are
not covered by output cleanup (that arrives with milestone 5); this service
only expires generated output assets.
"""

from __future__ import annotations

import argparse
import time

from sqlalchemy import and_, or_, select

from .config import Settings, get_settings
from .db import Db
from .models import Asset, Job, Worker, utcnow
from .orchestration import get_job_by_id
from .storage import Storage, build_storage, delete_asset_blobs

STALE_WORKER_HOURS = 24


def purge_stale_workers(db: Db, now=None) -> int:
    """Delete worker rows whose last heartbeat is older than 24 hours (or null).

    Runs on every maintenance tick (the hub schedules the loop at 600 s, so the
    admin GPU Workers page self-cleans every 10 minutes without a manual click).
    """
    from datetime import timedelta

    now = now or utcnow()
    cutoff = now - timedelta(hours=STALE_WORKER_HOURS)
    with db.session() as session:
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
    return len(rows)


def expire_once(db: Db, storage: Storage, now=None) -> int:
    """Reclaim object-storage bytes for assets whose retention or Trash window elapsed.

    Two independent triggers:
      * ``expires_at <= now``  — the ordinary retention expiry for live outputs.
      * ``purge_after <= now`` — the 48-hour Trash window after a soft delete.

    A row is purged at most once: ``purged_at`` marks the bytes as gone while the
    metadata row is kept (the admin forensic catalog still lists it). Expired live
    assets are also marked ``deleted_at`` so they leave the owner's library.
    """
    now = now or utcnow()
    purged = 0
    skipped = 0
    with db.session() as session:
        rows = list(
            session.execute(
                select(Asset).where(
                    Asset.purged_at.is_(None),
                    or_(
                        and_(Asset.expires_at.is_not(None), Asset.expires_at <= now),
                        and_(Asset.purge_after.is_not(None), Asset.purge_after <= now),
                    ),
                )
            ).scalars()
        )
        for asset in rows:
            try:
                delete_asset_blobs(storage, asset.storage_key)
            except OSError as exc:
                # Cross-host NFS writes can leave bytes owned by another uid; the
                # storage user may not be able to unlink them. Never crash the
                # reaper: leave purged_at unset (retry next pass) and keep going.
                skipped += 1
                print(f"purge skipped for asset {asset.id} ({asset.storage_key}): {exc}")
                continue
            asset.purged_at = utcnow()
            if asset.deleted_at is None:
                asset.deleted_at = utcnow()
            purged += 1
            job = get_job_by_id(session, asset.job_id)
            if job is not None and asset.expires_at is not None:
                job.assets_expired_at = asset.expires_at
        session.commit()
    if skipped:
        print(f"expire_once: purged {purged}, skipped {skipped} un-deletable object(s)")
    return purged


def reap_orphaned_attempts(db: Db, settings: Settings, now=None) -> int:
    """Fail model-lab attempts whose worker died mid-run (orphaned 'running').

    A 'running' attempt is legitimate only while a fleet node is actively
    training it with a fresh heartbeat. If the worker was recreated or killed,
    no such node exists (or its heartbeat went stale), so the attempt is
    orphaned and its budget reservation is released by settling it as failed.
    Runs in the maintenance service so it recovers even when no training worker
    is alive to notice.
    """
    from datetime import datetime, timedelta, timezone

    from .fleet_nodes import NODE_STATES
    from .model_lab_train import settle_attempt
    from .models import FleetNode, MlBudget, MlTrainingAttempt

    def _aware(dt: datetime | None) -> datetime | None:
        # SQLite (tests) round-trips naive datetimes; treat them as UTC.
        if dt is None:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    now = _aware(now or utcnow())
    training_states = ("draining", "training_reserved", "active", "cleanup")
    assert training_states and all(s in NODE_STATES for s in training_states)
    cutoff = now - timedelta(seconds=max(1.0, settings.node_stale_seconds))
    grace = timedelta(minutes=2)
    reaped = 0
    with db.session() as session:
        rows = session.execute(
            select(MlTrainingAttempt).where(
                MlTrainingAttempt.state == "running",
                MlTrainingAttempt.settled.is_(False),
            )
        ).scalars().all()
        for attempt in rows:
            created = _aware(attempt.created_at)
            if created and now - created < grace:
                continue  # freshly claimed: let the worker wire up its node
            node = session.execute(
                select(FleetNode).where(
                    FleetNode.exclusive_attempt_id == attempt.id,
                    FleetNode.state.in_(training_states),
                )
            ).scalars().first()
            if node is not None and _aware(node.heartbeat_at) is not None \
                    and _aware(node.heartbeat_at) >= cutoff:
                continue
            budget = session.get(MlBudget, attempt.budget_id)
            settle_attempt(session, attempt, state="failed",
                           error="worker lost: no active training node",
                           budget=budget)
            reaped += 1
    return reaped


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenAudioLab maintenance")
    parser.add_argument("--once", action="store_true", help="run one expiry pass and exit")
    parser.add_argument("--interval", type=float, default=3600.0)
    args = parser.parse_args()

    settings: Settings = get_settings()
    db = Db(settings.database_url)
    storage = build_storage(settings)
    while True:
        count = expire_once(db, storage)
        if count:
            print(f"expired {count} asset(s)")
        purged = purge_stale_workers(db)
        if purged:
            print(f"purged {purged} stale worker(s)")
        reaped = reap_orphaned_attempts(db, settings)
        if reaped:
            print(f"reaped {reaped} orphaned model-lab attempt(s)")
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
