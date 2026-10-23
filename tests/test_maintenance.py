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
        job_id = None
        if with_node is not None:
            job = Job(id=new_uuid(), owner_id="model-lab", operation="model_lab.train",
                      model_id="training", model_revision="m", status="running",
                      request_json={}, request_hash="h", idempotency_key=f"mt-{new_uuid()}")
            session.add(job)
            session.flush()
            job_id = job.id
            session.add(JobAttempt(id=new_uuid(), job_id=job_id, attempt_number=1,
                                   worker_id="w-m", lease_token="t-m", status="running",
                                   heartbeat_at=utcnow() if not stale_node
                                   else utcnow() - timedelta(hours=2)))
        att = MlTrainingAttempt(id=new_uuid(), dataset_id=ds.id, budget_id=budget.id,
                                job_id=job_id, state=state, reserved_usd=0.25,
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


def _attempt_with_job(client, *, lease_fresh=True):
    from datetime import timedelta

    from app.models import (Job, JobAttempt, MlBudget, MlDataset, MlSource,
                            MlTrainingAttempt, new_uuid, utcnow)

    with client.app.state.db.session() as session:
        budget = MlBudget(id=new_uuid(), name=f"rb-{next(_SEQ)}", max_hours=6.0,
                          max_spend_usd=3.0, reserved_usd=0.25)
        src = MlSource(id=new_uuid(), name=f"rb-s{next(_SEQ)}", status="approved")
        session.add_all([budget, src])
        session.commit()
        ds = MlDataset(id=new_uuid(), name="rb-d", kind="style", frozen_sha256="f",
                       manifest_json={"entries": []})
        job = Job(id=new_uuid(), owner_id="model-lab", operation="model_lab.train",
                  model_id="training", model_revision="m", status="running",
                  request_json={}, request_hash="h", idempotency_key=f"rb-{new_uuid()}")
        att = MlTrainingAttempt(id=new_uuid(), dataset_id=ds.id, budget_id=budget.id,
                                job_id=job.id, state="running", reserved_usd=0.25,
                                created_at=utcnow() - timedelta(minutes=30))
        lease = JobAttempt(id=new_uuid(), job_id=job.id, attempt_number=1,
                           worker_id="w-x", lease_token="t", status="running",
                           heartbeat_at=utcnow() if lease_fresh
                           else utcnow() - timedelta(hours=2))
        session.add_all([ds, job, att, lease])
        session.commit()
        return att.id, budget.id, job.id


def test_reaper_respects_live_job_lease(client) -> None:
    from app.maintenance import reap_orphaned_attempts

    att_id, budget_id, _ = _attempt_with_job(client, lease_fresh=True)
    assert reap_orphaned_attempts(client.app.state.db, client.app.state.settings) == 0
    from app.models import MlTrainingAttempt
    with client.app.state.db.session() as session:
        assert session.get(MlTrainingAttempt, att_id).state == "running"


def test_reaper_reaps_when_lease_stale(client) -> None:
    from app.maintenance import reap_orphaned_attempts

    att_id, budget_id, _ = _attempt_with_job(client, lease_fresh=False)
    assert reap_orphaned_attempts(client.app.state.db, client.app.state.settings) == 1
    from app.models import MlBudget, MlTrainingAttempt
    with client.app.state.db.session() as session:
        assert session.get(MlTrainingAttempt, att_id).state == "failed"
        for b in session.query(MlBudget).all():
            if b.id == budget_id:
                assert b.reserved_usd == 0.0


def test_reconcile_budget_from_durable_attempts(client) -> None:
    from datetime import timedelta

    from app.maintenance import reconcile_budget
    from app.models import MlBudget, MlTrainingAttempt, new_uuid, utcnow

    att_id, budget_id, job_id = _attempt_with_job(client, lease_fresh=True)
    with client.app.state.db.session() as session:
        att = session.get(MlTrainingAttempt, att_id)
        att.state, att.settled, att.hours, att.spend_usd = "done", True, 1.25, 0.1
        stray = MlTrainingAttempt(id=new_uuid(), dataset_id=att.dataset_id,
                                  budget_id=budget_id, state="queued", reserved_usd=0.25,
                                  created_at=utcnow() - timedelta(days=1))
        session.add(stray)
        session.commit()
    reconcile_budget(client.app.state.db)
    with client.app.state.db.session() as session:
        b = session.get(MlBudget, budget_id)
        assert b.used_hours == 1.25 and b.spent_usd == 0.1 and b.reserved_usd == 0.25
