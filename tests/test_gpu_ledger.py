"""M3: offer filters, presets, cost ledger, deployment form."""

from __future__ import annotations

import pytest

_SEQ = iter(range(1000, 99999))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    email = f"m3admin{next(_SEQ)}@example.com"
    resp = client.post("/api/v1/auth/register",
                       json={"email": email, "username": f"m3a{next(_SEQ)}",
                             "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def _offer(**over) -> dict:
    base = {"id": next(_SEQ), "gpu_name": "RTX 4090", "gpu_ram": 24576,
            "cuda_max_good": 12.8, "geolocation": "Chicago, US",
            "reliability2": 0.99, "inet_down": 1200.0, "inet_up": 800.0,
            "disk_space": 200.0, "cpu_ram": 131072, "dph_total": 0.18,
            "compute_cap": 8.9, "verified": True, "rentable": True}
    base.update(over)
    return base


def test_normalize_exposes_ram() -> None:
    from app import vast_offers as vo

    offer = vo.normalize(_offer())
    assert offer["ram_gb"] == 128.0


def test_new_offer_filters() -> None:
    from app import vast_offers as vo

    region = {"countries": ["US"]}
    crit = {"gpu_model": "A100", "min_disk_gb": None, "min_ram_gb": None, **region}
    res = vo.rank([_offer()], crit, limit=10)
    assert res["eligible_count"] == 0
    assert res["excluded"]["GPU_MODEL_EXCLUDED"] == 1

    crit = {"gpu_model": "4090", "min_disk_gb": 500, "min_ram_gb": None, **region}
    res = vo.rank([_offer()], crit, limit=10)
    assert res["excluded"].get("DISK_BELOW_MINIMUM") == 1

    crit = {"gpu_model": None, "min_disk_gb": None, "min_ram_gb": 256, **region}
    res = vo.rank([_offer()], crit, limit=10)
    assert res["excluded"].get("RAM_BELOW_MINIMUM") == 1

    crit = {"gpu_model": "4090", "min_disk_gb": 100, "min_ram_gb": 64, **region}
    res = vo.rank([_offer()], crit, limit=10)
    assert res["eligible_count"] == 1


def test_presets_roundtrip_and_validation(client) -> None:
    presets = [{"name": "24gb-training", "params": {"min_vram": 24, "max_dph": 0.25}},
               {"name": "48gb-xl", "params": {"min_vram": 48}}]
    r = client.put("/api/v1/admin/gpu-fleet/presets", json={"presets": presets})
    assert r.status_code == 200
    got = client.get("/api/v1/admin/gpu-fleet/presets").json()["presets"]
    assert got == presets
    dup = client.put("/api/v1/admin/gpu-fleet/presets",
                     json={"presets": [{"name": "a", "params": {}},
                                       {"name": "a", "params": {}}]})
    assert dup.status_code == 422
    bad = client.put("/api/v1/admin/gpu-fleet/presets",
                     json={"presets": [{"name": "x"}]})
    assert bad.status_code == 422


def test_deploy_form_creates_deployment_and_ledger(client) -> None:
    r = client.post("/api/v1/admin/gpu-fleet/deploy",
                    json={"offer_id": "off-77", "purpose": "training",
                          "name": "train-node-1", "dph": 0.2, "max_spend_usd": 3.0})
    assert r.status_code == 201
    body = r.json()
    assert body["state"] == "REQUESTED" and body["ledger"]["state"] == "open"
    led = client.get("/api/v1/admin/gpu-fleet/ledger").json()
    assert led["open_entries"] >= 1
    assert any(e["vast_instance_id"] == body["vast_instance_id"] for e in led["entries"])


def test_ledger_close_is_exact_and_idempotent(client) -> None:
    from datetime import timedelta

    from app.gpu_ledger import close_entry, open_entry
    from app.models import GpuCostLedger, new_uuid, utcnow

    iid = f"led-{next(_SEQ)}"
    with client.app.state.db.session() as session:
        entry = open_entry(session, iid, purpose="training", dph=0.2)
        entry.opened_at = utcnow() - timedelta(hours=2)
        session.commit()
        eid = entry.id
    with client.app.state.db.session() as session:
        closed = close_entry(session, iid)
        assert closed is not None and closed.id == eid
        assert abs(closed.hours - 2.0) < 0.01
        assert abs(closed.usd - 0.4) < 0.005
        assert close_entry(session, iid) is None  # idempotent
        with_session_check = session.get(GpuCostLedger, eid)
        assert with_session_check.state == "closed"


def test_worker_stop_closes_ledger(client, monkeypatch) -> None:
    from app.gpu_ledger import open_entry
    from app.models import GpuCostLedger, VastInstance
    from sqlalchemy import select

    monkeypatch.setattr("app.routes.admin._vast_request",
                        lambda request, method, path, body=None: {})
    host = f"gpu-stop-{next(_SEQ)}"
    with client.app.state.db.session() as session:
        inst = VastInstance(vast_instance_id=f"stop-{next(_SEQ)}",
                            hostname=host, dph=0.2, state="running")
        session.add(inst)
        session.commit()
        vid = inst.vast_instance_id
        open_entry(session, vid, purpose="auto", dph=0.2)
    r = client.post(f"/api/v1/admin/gpu-fleet/workers/acestep-{host}-1/stop")
    assert r.status_code == 200
    with client.app.state.db.session() as session:
        entry = session.execute(
            select(GpuCostLedger).where(GpuCostLedger.vast_instance_id == vid)
        ).scalars().one()
        assert entry.state == "closed" and entry.usd is not None
