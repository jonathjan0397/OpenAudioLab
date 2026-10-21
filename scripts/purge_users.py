#!/usr/bin/env python3
"""Hard-delete test/scaffolding users + cascade + storage purge.

DRY-RUN by default (lists exactly what would be destroyed). Only `--execute` deletes.
Because the schema is FK-free, we delete children by owner_id / derived id-sets, then
remove the user's stored bytes (assets' storage_key + owners//uploads/ prefixes).

    set -a; . .env.backend; set +a
    .venv/bin/python scripts/purge_users.py --user <id-or-email> [...]        # dry run
    .venv/bin/python scripts/purge_users.py --execute --user <id> [...]       # irreversible
"""
from __future__ import annotations

import argparse
import sys

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import Db
from app.models import ApiKey, Asset, Job, User
from app.storage import build_storage

# tables keyed by owner_id string 'usr_<id>'
_OWNER_TABLES = [
    "jobs", "assets", "idempotency_records", "projects", "project_versions",
    "upload_sessions", "artist_profiles", "artist_profile_versions", "rights_records",
    "datasets", "dataset_tracks", "dataset_versions", "favorites", "artist_follows",
    "api_keys", "credit_entries", "billing_events", "workspaces", "workspace_songs",
    "artist_songs", "quotes",
]
# job-linked tables (job_id)
_JOB_TABLES = ["job_attempts", "job_events", "outbox_records"]
# user_id-keyed (not owner_id)
_USERID_TABLES = ["user_sessions", "auth_tokens", "subscription_periods"]


def _tables_with_column(session, column: str) -> set[str]:
    return {
        r[0] for r in session.execute(
            sa.text(
                "select table_name from information_schema.columns where table_schema='public' and column_name=:c"
            ),
            {"c": column},
        )
    }


def _resolve(session: Session, ident: str) -> User | None:
    u = session.get(User, ident)
    if u is None:
        u = session.execute(sa.select(User).where(User.email == ident)).scalar_one_or_none()
    return u


def _preview_and_delete(session: Session, storage, user: User, execute: bool) -> dict:
    owner = f"usr_{user.id}"
    job_ids = [r[0] for r in session.execute(sa.select(Job.id).where(Job.owner_id == owner))]
    asset_keys = [r[0] for r in session.execute(sa.select(Asset.storage_key).where(Asset.owner_id == owner))]
    asset_ids = [r[0] for r in session.execute(sa.select(Asset.id).where(Asset.owner_id == owner))]
    bytes_sum = session.execute(sa.select(sa.func.coalesce(sa.func.sum(Asset.bytes), 0)).where(Asset.owner_id == owner)).scalar() or 0
    storage_prefixes = [f"owners/{owner}", f"uploads/{owner}"]
    obj_keys: list[str] = []
    for p in storage_prefixes:
        try:
            obj_keys += storage.list_prefix(p)
        except Exception:  # noqa: BLE001 - best effort on prefix scan
            pass
    summary = {
        "user": f"{user.email} (role={user.role} plan={user.plan} state={user.state})",
        "owner_id": owner,
        "jobs": len(job_ids), "assets": len(asset_ids),
        "asset_bytes": int(bytes_sum), "storage_objects": len(obj_keys),
    }
    if not execute:
        return summary

    def _del(table: str, column: str, values: list[str]):
        if not values:
            return
        session.execute(sa.text(f"DELETE FROM {table} WHERE {column} IN :v").bindparams(v=tuple(values)))

    owner_tabs = _tables_with_column(session, "owner_id")
    user_tabs = _tables_with_column(session, "user_id")

    for t in _JOB_TABLES:
        if t in owner_tabs or t in _tables_with_column(session, "job_id"):
            _del(t, "job_id", job_ids)
    for t in _OWNER_TABLES:
        if t in owner_tabs:
            session.execute(sa.text(f"DELETE FROM {t} WHERE owner_id = :o"), {"o": owner})
    if "favorites" in owner_tabs:
        _del("favorites", "asset_id", asset_ids)
    for t in _USERID_TABLES:
        if t in user_tabs:
            session.execute(sa.text(f"DELETE FROM {t} WHERE user_id = :o"), {"o": user.id})
    if "guest_sessions" in owner_tabs or "guest_sessions" in user_tabs:
        gs_cols = _tables_with_column(session, "claimed_user_id")
        if "guest_sessions" in gs_cols:
            session.execute(sa.text("DELETE FROM guest_sessions WHERE claimed_user_id = :o"), {"o": user.id})
    if "abuse_reports" in owner_tabs:
        session.execute(sa.text("DELETE FROM abuse_reports WHERE reporter_owner_id = :o"), {"o": owner})
    # storage bytes
    for k in sorted(set(asset_keys) | set(obj_keys)):
        try:
            storage.delete(k)
        except Exception as exc:
            print(f"  ! storage.delete {k}: {exc}", file=sys.stderr)
    session.delete(user)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Purge test users (dry-run by default).")
    ap.add_argument("--user", action="append", required=True, help="user id or email (repeatable)")
    ap.add_argument("--execute", action="store_true", help="actually delete (irreversible)")
    args = ap.parse_args(argv)

    settings = get_settings()
    db = Db(settings.database_url)
    storage = build_storage(settings)
    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"=== purge_users ({mode}) backend={settings.storage_backend} ===")
    with db.session() as session:
        for ident in args.user:
            user = _resolve(session, ident)
            if user is None:
                print(f"!! not found: {ident}")
                continue
            summary = _preview_and_delete(session, storage, user, args.execute)
            print(f"[{mode}] {summary}")
        if args.execute:
            session.commit()
            print("committed.")
        else:
            session.rollback()
            print("(dry run; nothing deleted. Re-run with --execute to apply.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
