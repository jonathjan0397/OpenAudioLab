"""Retention maintenance: seven-day output expiry and object deletion.

Active artist-profile artifacts and explicitly retained training datasets are
not covered by output cleanup (that arrives with milestone 5); this service
only expires generated output assets.
"""

from __future__ import annotations

import argparse
import time

from sqlalchemy import select

from .config import Settings, get_settings
from .db import Db
from .models import Asset, Job, utcnow
from .orchestration import get_job_by_id
from .storage import Storage, build_storage


def expire_once(db: Db, storage: Storage, now=None) -> int:
    now = now or utcnow()
    expired = 0
    with db.session() as session:
        rows = list(
            session.execute(
                select(Asset).where(Asset.deleted_at.is_(None), Asset.expires_at.is_not(None), Asset.expires_at <= now)
            ).scalars()
        )
        for asset in rows:
            storage.delete(asset.storage_key)
            asset.deleted_at = utcnow()
            expired += 1
            job = get_job_by_id(session, asset.job_id)
            if job is not None:
                job.assets_expired_at = asset.expires_at
        session.commit()
    return expired


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
