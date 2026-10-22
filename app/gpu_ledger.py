"""GPU cost ledger: durable spend entries with idempotent settlement.

An entry opens when a node is deployed and closes when it stops or is
destroyed. Closing computes hours x dph exactly once (replays are no-ops),
so the ledger — not the provider UI — is the accounting record.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import GpuCostLedger, new_uuid, utcnow


def open_entry(session: Session, vast_instance_id: str, *, purpose: str = "auto",
               dph: float | None = None, source: str = "deploy") -> GpuCostLedger:
    entry = GpuCostLedger(id=new_uuid(), vast_instance_id=vast_instance_id,
                          purpose=purpose, dph=dph, source=source)
    session.add(entry)
    session.commit()
    return entry


def close_entry(session: Session, vast_instance_id: str) -> GpuCostLedger | None:
    """Close the open entry for an instance; idempotent (returns None if none)."""
    entry = session.execute(
        select(GpuCostLedger).where(GpuCostLedger.vast_instance_id == vast_instance_id,
                                    GpuCostLedger.state == "open")
        .order_by(GpuCostLedger.opened_at.desc())).scalars().first()
    if entry is None:
        return None
    entry.state = "closed"
    entry.closed_at = utcnow()
    if entry.dph is not None:
        def _naive(dt):
            return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt
        hours = max(0.0, (_naive(entry.closed_at) - _naive(entry.opened_at))
                    .total_seconds() / 3600.0)
        entry.hours = round(hours, 4)
        entry.usd = round(hours * entry.dph, 4)
    session.commit()
    return entry


def entry_view(entry: GpuCostLedger) -> dict:
    return {"id": entry.id, "vast_instance_id": entry.vast_instance_id,
            "purpose": entry.purpose, "dph": entry.dph, "state": entry.state,
            "opened_at": entry.opened_at.isoformat() if entry.opened_at else None,
            "closed_at": entry.closed_at.isoformat() if entry.closed_at else None,
            "hours": entry.hours, "usd": entry.usd, "source": entry.source}


def ledger_summary(session: Session) -> dict:
    entries = session.execute(
        select(GpuCostLedger).order_by(GpuCostLedger.opened_at.desc())).scalars().all()
    closed_usd = round(sum(e.usd or 0.0 for e in entries if e.state == "closed"), 4)
    open_count = sum(1 for e in entries if e.state == "open")
    by_purpose: dict[str, float] = {}
    for e in entries:
        if e.state == "closed":
            by_purpose[e.purpose] = round(by_purpose.get(e.purpose, 0.0) + (e.usd or 0.0), 4)
    return {"entries": [entry_view(e) for e in entries[:200]],
            "closed_total_usd": closed_usd, "open_entries": open_count,
            "closed_by_purpose_usd": by_purpose}
