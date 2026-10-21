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
from .models import Asset, Job, utcnow
from .orchestration import get_job_by_id
from .storage import Storage, build_storage, delete_asset_blobs


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
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
