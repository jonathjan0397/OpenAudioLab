"""Maintenance reaper: orphaned 'running' model-lab attempts release their budget."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import FleetNode, MlBudget, MlDataset, MlTrainingAttempt, new_uuid, utcnow
from app.maintenance import reap_orphaned_attempts

_SEQ = iter(range(1, 10000))


def _attempt(client, *, state="running", with_node=None, stale_node=False):
    from app.models import MlRecording, MlSource

    db = client.app.state.db
    budget_id = f"b-{next(_SEQ)}"
    with db.session() as session:
        budget = MlBudget(id=budget_id, name=f"pilot-{next(_SEQ)}",
                          max_hours=6.0, max_spend_usd=3.0)
        session.add(budget)
        src = MlSource(id=new_uuid(), name="src", status="approved")
        rec = MlRecording(id=new_uuid(), source_id=src.id, path="/x/a.mp3",
                          sha256="sha-a", duration_seconds=10.0,
                          review_status="approved", dataset_eligible=True)
        ds = MlDataset(id=new_uuid(), name="ds", frozen_sha256="f",
                       manifest_json={"entries": []})
        att = MlTrainingAttempt(id=new_uuid(), dataset_id=ds.id, budget_id=budget.id,
                                state=state, reserved_usd=0.25,
                                created_at=utcnow() - timedelta(minutes=10))
        budget.reserved_usd = 0.25
        session.add_all([src, rec, ds, att])
        if with_node is not None:
            hb = utcnow()
            if stale_node:
                hb = utcnow() - timedelta(hours=2)
            session.add(FleetNode(id=with_node, exclusive_attempt_id=att.id,
                                  state="active", heartbeat_at=hb))
        session.commit()
        return att.id, budget.id


def test_reap_orphaned_running_attempt_releases_budget(client) -> None:
    att_id, _ = _attempt(client)
    n = reap_orphaned_attempts(client.app.state.db, client.app.state.settings)
    assert n == 1
    with client.app.state.db.session() as session:
        att = session.get(MlTrainingAttempt, att_id)
        assert att.state == "failed" and att.settled
        assert "worker lost" in (att.error or "")
        b = session.get(MlBudget, att.budget_id)
        assert b.reserved_usd == 0.0


def test_reap_keeps_attempt_with_live_node(client) -> None:
    att_id, _ = _attempt(client, with_node="node-live")
    n = reap_orphaned_attempts(client.app.state.db, client.app.state.settings)
    assert n == 0
    with client.app.state.db.session() as session:
        att = session.get(MlTrainingAttempt, att_id)
        assert att.state == "running" and not att.settled


def test_reap_orphans_node_with_stale_heartbeat(client) -> None:
    att_id, _ = _attempt(client, with_node="node-stale", stale_node=True)
    n = reap_orphaned_attempts(client.app.state.db, client.app.state.settings)
    assert n == 1
    with client.app.state.db.session() as session:
        assert session.get(MlTrainingAttempt, att_id).state == "failed"


def test_reap_grace_skips_fresh_attempt(client) -> None:
    from app.models import MlTrainingAttempt

    att_id, _ = _attempt(client)
    with client.app.state.db.session() as session:
        att = session.get(MlTrainingAttempt, att_id)
        att.created_at = utcnow()  # just claimed
        session.commit()
    assert reap_orphaned_attempts(client.app.state.db, client.app.state.settings) == 0
