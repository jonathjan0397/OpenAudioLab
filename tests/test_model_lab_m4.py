"""Model Lab M4: frozen datasets, pilot budget gate, attempt accounting."""

from __future__ import annotations

import pytest

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    email = f"ml4admin{next(_SEQ)}@example.com"
    resp = client.post("/api/v1/auth/register",
                       json={"email": email, "username": f"ml4a{next(_SEQ)}",
                             "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def _approved_recording(client, review="approved", scopes=("recording",)):
    from app.models import MlRecording, MlRightsRecord, MlSource, new_uuid

    with client.app.state.db.session() as session:
        src = MlSource(id=new_uuid(), name=f"t-src-{next(_SEQ)}", status="approved")
        session.add(src)
        session.commit()
        rec = MlRecording(id=new_uuid(), source_id=src.id, path=f"/x/{next(_SEQ)}.mp3",
                          sha256=f"t-sha-{next(_SEQ)}", duration_seconds=180.0,
                          review_status=review)
        session.add(rec)
        session.commit()
        for scope in scopes:
            session.add(MlRightsRecord(id=new_uuid(), recording_id=rec.id, holder="owner",
                                       scope=scope, evidence="test declaration"))
        session.commit()
        return rec.id


def test_budget_defaults_and_validation(client) -> None:
    b = client.get("/api/v1/admin/model-lab/budget").json()
    assert b == {"name": "pilot", "max_hours": 6.0, "max_spend_usd": 3.0,
                 "used_hours": 0.0, "spent_usd": 0.0, "reserved_usd": 0.0,
                 "state": "open"}
    bad = client.put("/api/v1/admin/model-lab/budget", json={"max_hours": -1})
    assert bad.status_code == 422
    r = client.put("/api/v1/admin/model-lab/budget", json={"max_hours": 2.0})
    assert r.status_code == 200 and r.json()["max_hours"] == 2.0


def test_dataset_freeze_requires_approval(client) -> None:
    good = _approved_recording(client)
    pending = _approved_recording(client, review="unreviewed")
    r = client.post("/api/v1/admin/model-lab/datasets",
                    json={"name": "pilot-1", "recording_ids": [good, pending]})
    assert r.status_code == 422  # pending recording not approved
    r = client.post("/api/v1/admin/model-lab/datasets",
                    json={"name": "pilot-1", "recording_ids": [good]})
    assert r.status_code == 201 and r.json()["recording_count"] == 1
    empty = client.post("/api/v1/admin/model-lab/datasets",
                        json={"name": "empty", "recording_ids": []})
    assert empty.status_code == 422


def test_freeze_is_deterministic(client) -> None:
    from app.model_lab_train import freeze_dataset

    ids = [_approved_recording(client) for _ in range(2)]
    with client.app.state.db.session() as session:
        a = freeze_dataset(session, "d-a", ids)
        b = freeze_dataset(session, "d-b", list(reversed(ids)))
        assert a.frozen_sha256 == b.frozen_sha256  # order-independent manifest hash


def test_train_dispatch_and_budget_gate(client) -> None:
    from app.models import Job, OutboxRecord

    ids = [_approved_recording(client)]
    ds = client.post("/api/v1/admin/model-lab/datasets",
                     json={"name": "gate-1", "recording_ids": ids}).json()
    r = client.post(f"/api/v1/admin/model-lab/datasets/{ds['id']}/train")
    assert r.status_code == 202
    body = r.json()
    with client.app.state.db.session() as session:
        job = session.query(Job).filter_by(id=body["job_id"]).first()
        assert job.operation == "model_lab.train" and job.model_id == "training"
        assert session.query(OutboxRecord).filter_by(job_id=job.id).count() == 1
    # exhaust the budget -> further dispatch refused explicitly
    client.put("/api/v1/admin/model-lab/budget", json={"max_hours": 0.0})
    blocked = client.post(f"/api/v1/admin/model-lab/datasets/{ds['id']}/train")
    assert blocked.status_code == 409 and blocked.json()["error"]["code"] == "BUDGET_EXHAUSTED"


def test_attempt_completion_books_budget(client) -> None:
    from app.model_lab_train import complete_attempt, get_budget
    from app.models import MlDataset, MlTrainingAttempt, new_uuid

    with client.app.state.db.session() as session:
        ds = MlDataset(id=new_uuid(), name="acct-1", frozen_sha256="f" * 64)
        session.add(ds)
        session.commit()
        budget = get_budget(session)
        budget.max_hours, budget.max_spend_usd = 2.0, 1.0
        session.commit()
        attempt = MlTrainingAttempt(id=new_uuid(), dataset_id=ds.id, budget_id=budget.id)
        session.add(attempt)
        session.commit()
        out = complete_attempt(session, attempt, state="done", hours=2.0, spend_usd=0.9,
                               budget=budget)
        assert out["state"] == "done"
        assert budget.used_hours == 2.0 and budget.state == "exhausted"


def test_completion_rejects_unknown_state(client) -> None:
    from app.model_lab_train import BudgetError, complete_attempt, get_budget
    from app.models import MlDataset, MlTrainingAttempt, new_uuid

    with client.app.state.db.session() as session:
        ds = MlDataset(id=new_uuid(), name="acct-2", frozen_sha256="a" * 64)
        session.add(ds)
        budget = get_budget(session)
        attempt = MlTrainingAttempt(id=new_uuid(), dataset_id=ds.id, budget_id=budget.id)
        session.add(attempt)
        session.commit()
        with pytest.raises(BudgetError):
            complete_attempt(session, attempt, state="bogus", budget=budget)
