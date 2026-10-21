"""GPU orchestration M1: Smart Model Queue Manager (SMQM) selection tests."""

from __future__ import annotations

from sqlalchemy import select

from app.engine_acestep import SubmitResult
from app.engine_worker import EngineWorker
from app.models import Job, utcnow
from conftest import auth, submit
from test_engine_worker import FakeAdapter

TURBO = "acestep-v15-turbo"


class FakeEngineProcess:
    """Mimics AceStepProcess swap semantics: a model change stops the server."""

    def __init__(self, model: str) -> None:
        self.model = model
        self.stops = 0

    def is_running(self) -> bool:
        return True

    def ensure_running(self, model: str | None = None) -> None:
        if model and model != self.model:
            self.stops += 1
            self.model = model

    def stop(self) -> None:
        self.stops += 1


def _worker(orch, adapter, engine=None) -> EngineWorker:
    return EngineWorker(
        orch.db, orch.queue, orch.storage, adapter, orch.settings,
        worker_id="test-smqm", engine_process=engine,
    )


def _submit(client, orch, title: str, family: str = "turbo") -> str:
    r = submit(client, key=f"smqm-{title}", title=title)
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    if family != "turbo":
        with orch.db.session() as session:
            job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
            job.request_json = {
                **(job.request_json or {}),
                "_admission": {"family": family, "engine_model": f"acestep-v15-{family}-x",
                               "execution_profile_id": f"{family}-v1"},
            }
            session.commit()
    return job_id


def _status(client, orch, title: str) -> str:
    with orch.db.session() as session:
        for j in session.execute(select(Job)).scalars():
            if (j.request_json or {}).get("title") == title:
                return j.status
    raise AssertionError(f"no job titled {title}")


def _outcomes(n: int) -> list:
    out: list = []
    for i in range(n):
        out.append(SubmitResult(task_id=f"smqm-{i}"))
        out.append(("succeeded", [{"file": "/v1/audio?path=x", "dit_model": "m"}]))
    return out


def _always_runnable(worker: EngineWorker) -> EngineWorker:
    worker._can_run_profile = lambda adm: (True, "")  # type: ignore[method-assign]
    return worker


def test_same_model_jobs_run_consecutively(client, orch) -> None:
    """§19.1: with Turbo loaded, Turbo jobs are preferred over the older XL job."""
    _submit(client, orch, "q1-xl", "xl")
    _submit(client, orch, "q1-t1", "turbo")
    _submit(client, orch, "q1-t2", "turbo")
    orch.dispatcher.publish_once()
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(3)), FakeEngineProcess(TURBO)))
    assert worker.run_once() is True
    assert _status(client, orch, "q1-t1") == "succeeded"
    assert _status(client, orch, "q1-xl") == "queued"
    assert worker.run_once() is True
    assert _status(client, orch, "q1-t2") == "succeeded"
    assert worker.run_once() is True  # turbo exhausted -> immediate switch to XL
    assert _status(client, orch, "q1-xl") == "succeeded"


def test_no_unnecessary_checkpoint_reload(client, orch) -> None:
    """§19.2: consecutive same-model jobs must not restart the engine."""
    _submit(client, orch, "q2-t1", "turbo")
    _submit(client, orch, "q2-t2", "turbo")
    orch.dispatcher.publish_once()
    engine = FakeEngineProcess(TURBO)
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(2)), engine))
    assert worker.run_once() is True
    assert worker.run_once() is True
    assert engine.stops == 0


def test_immediate_switch_when_loaded_exhausted(client, orch) -> None:
    """§19.3: no waiting for the idle timer when only another model has work."""
    _submit(client, orch, "q3-xl", "xl")
    orch.dispatcher.publish_once()
    engine = FakeEngineProcess(TURBO)
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(1)), engine))
    assert worker.run_once() is True
    assert _status(client, orch, "q3-xl") == "succeeded"
    assert engine.stops == 1  # exactly one swap, at claim time


def test_fairness_batch_cap_forces_switch(client, orch, monkeypatch) -> None:
    """§19.4: continuous Turbo demand cannot starve XL beyond the batch window."""
    monkeypatch.setattr(orch.settings, "model_batch_max_jobs", 2)
    _submit(client, orch, "q4-xl", "xl")
    _submit(client, orch, "q4-t1", "turbo")
    _submit(client, orch, "q4-t2", "turbo")
    _submit(client, orch, "q4-t3", "turbo")
    orch.dispatcher.publish_once()
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(3)), FakeEngineProcess(TURBO)))
    assert worker.run_once() is True
    assert _status(client, orch, "q4-t1") == "succeeded"
    assert worker.run_once() is True
    assert _status(client, orch, "q4-t2") == "succeeded"
    assert worker.run_once() is True  # batch cap reached -> XL goes first
    assert _status(client, orch, "q4-xl") == "succeeded"
    assert _status(client, orch, "q4-t3") == "queued"


def test_incompatible_job_skipped_not_looped(client, orch) -> None:
    """§19.5: an XL job the worker cannot run stays queued; the Turbo job runs."""
    _submit(client, orch, "q5-xl", "xl")
    _submit(client, orch, "q5-t1", "turbo")
    orch.dispatcher.publish_once()
    worker = _worker(orch, FakeAdapter(_outcomes(1)), FakeEngineProcess(TURBO))
    assert worker.run_once() is True
    assert _status(client, orch, "q5-t1") == "succeeded"
    assert _status(client, orch, "q5-xl") == "queued"
    assert orch.queue.depth("oal:queue:ace-step-1.5") == 1  # XL hint preserved


def test_retry_backoff_skipped(client, orch) -> None:
    """§19.6: a job inside its retry window is not selected."""
    t1 = _submit(client, orch, "q6-t1", "turbo")
    _submit(client, orch, "q6-t2", "turbo")
    orch.dispatcher.publish_once()
    with orch.db.session() as session:
        job = session.execute(select(Job).where(Job.id == t1)).scalar_one()
        job.next_retry_at = utcnow().replace(year=utcnow().year + 1)
        session.commit()
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(1)), FakeEngineProcess(TURBO)))
    assert worker.run_once() is True
    assert _status(client, orch, "q6-t2") == "succeeded"
    assert _status(client, orch, "q6-t1") == "queued"


def test_lost_race_removes_stale_hint(client, orch, monkeypatch) -> None:
    """§19.8: a failed claim (another worker won) must LREM the consumed hint."""
    import app.engine_worker as ew

    _submit(client, orch, "q8-t1", "turbo")
    orch.dispatcher.publish_once()
    monkeypatch.setattr(ew, "claim_attempt", lambda *a, **k: None)
    worker = _always_runnable(_worker(orch, FakeAdapter([]), FakeEngineProcess(TURBO)))
    assert worker.run_once() is True
    assert orch.queue.depth("oal:queue:ace-step-1.5") == 0


def test_gpu_fleet_queues_endpoint(client) -> None:
    from app.models import User

    client.post("/api/v1/auth/logout")
    r = client.post(
        "/api/v1/auth/register",
        json={"email": "fleet@example.com", "username": "fleet", "password": "super-secret-1"},
    )
    uid = r.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()
    body = client.get("/api/v1/admin/gpu-fleet/queues")
    assert body.status_code == 200
    data = body.json()
    assert "models" in data and "workers" in data and "queue_depths" in data


# ---------------------------------------------------------------- M2: offers

def _raw(offer_id="o1", **kw):
    raw = {
        "id": offer_id, "gpu_name": "RTX 4090", "gpu_ram": 24 * 1024**3,
        "cuda_max_good": 12.8, "geolocation": "Los Angeles, US", "reliability2": 0.98,
        "inet_down": 1200.0, "inet_up": 300.0, "disk_space": 150.0,
        "dph_total": 0.20, "compute_cap": 8.9, "verified": True, "rentable": True,
    }
    raw.update(kw)
    return raw


def test_offer_hard_filters():
    from app import vast_offers as vo

    cases = [
        (_raw(dph_total=0.30), "PRICE_ABOVE_CEILING"),      # §19.18
        (_raw(gpu_ram=16 * 1024**3), "VRAM_BELOW_MINIMUM"),  # §19.19
        (_raw(cuda_max_good=12.4), "CUDA_UNSUPPORTED"),      # §19.20
        (_raw(geolocation="Toronto, CA"), None),             # §19.21 CA passes
        (_raw(geolocation="London, UK"), "OUTSIDE_REGION"),  # §19.21 UK fails
        (_raw(verified=False), "UNVERIFIED_HOST"),           # §19.22
        (_raw(reliability2=0.90), "LOW_RELIABILITY"),        # §19.23
        (_raw(disk_space=60.0), "DISK_INSUFFICIENT"),        # §19.25
    ]
    for raw, expected in cases:
        reason = vo.ineligible_reason(vo.normalize(raw), vo.criteria_defaults())
        assert reason == expected, (raw, reason)


def test_offer_missing_network_is_neutral_not_disqualified():
    from app import vast_offers as vo

    crit = vo.criteria_defaults()
    offer = vo.normalize(_raw(inet_down=None, inet_up=None))
    assert vo.ineligible_reason(offer, crit) is None  # §19.24 missing != excluded
    assert offer["download_mbps"] is None
    assert vo.est_ready_seconds(offer, 0.0) is None  # not reported -> not estimated


def test_offer_ranking_and_limits():
    from app import vast_offers as vo

    raws = [_raw(f"o{i}", dph_total=0.10 + i * 0.01) for i in range(14)]
    result = vo.rank(raws, limit=10)
    assert result["eligible_count"] == 14
    assert len(result["offers"]) == 10  # §19.26 subset when >10 eligible
    assert result["offers"][0]["rank"] == 1
    assert result["offers"][0]["dph"] <= result["offers"][-1]["dph"]  # cheaper ranks higher
    empty = vo.rank([_raw(dph_total=0.99)], limit=10)
    assert empty["offers"] == [] and empty["excluded"].get("PRICE_ABOVE_CEILING") == 1  # §19.27


def test_offer_expired_or_changed_revalidation():
    from app import vast_offers as vo

    # §19.28/29: deployment-time revalidation uses the same hard filters.
    snap = vo.normalize(_raw(dph_total=0.20))
    crit = vo.criteria_defaults()
    assert vo.ineligible_reason(snap, crit) is None
    changed = vo.normalize(_raw(dph_total=0.42))  # price jumped before deploy
    assert vo.ineligible_reason(changed, crit) == "PRICE_ABOVE_CEILING"


# ---------------------------------------------------------- M2: swappiness

def _fset(**kw):
    from app.fleet_settings import FLEET_DEFAULTS

    return {**FLEET_DEFAULTS, **kw}


def test_swappiness_local_sufficient_declines():
    import importlib.util, pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("autoscale_m2", root / "scripts" / "autoscale.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # §19.9: tiny queue -> remote startup not justified
    allow, decision, reason, _ = mod.swappiness_gate(120, 1, _fset(), 0, 0.0)
    assert allow is False and reason == "REMOTE_STARTUP_TOO_SLOW"
    # §19.10: heavy queue -> provision
    allow, decision, reason, _ = mod.swappiness_gate(3600, 20, _fset(), 0, 0.0)
    assert allow is True and reason == "REMOTE_FASTER"
    # §19.12: budget
    allow, _, reason, _ = mod.swappiness_gate(3600, 20, _fset(daily_burst_budget_usd=1.0), 0, 5.0)
    assert allow is False and reason == "BUDGET_EXHAUSTED"
    # capacity already present
    allow, _, reason, _ = mod.swappiness_gate(3600, 20, _fset(max_auto_burst_workers=1), 1, 0.0)
    assert allow is False and reason == "EXISTING_REMOTE_CAPACITY"
    # auto burst disabled
    allow, decision, reason, _ = mod.swappiness_gate(3600, 20, _fset(auto_burst_enabled=False), 0, 0.0)
    assert allow is False and decision == "HOLD" and reason == "AUTO_BURST_DISABLED"
    # §19 swappiness 0 -> depth policy provisions without cost-benefit
    allow, _, reason, _ = mod.swappiness_gate(60, 1, _fset(swappiness=0), 0, 0.0)
    assert allow is True and reason == "DEPTH_POLICY"


# ---------------------------------------------------------- M2: endpoints

def _login_admin(client, email):
    from app.models import User

    client.post("/api/v1/auth/logout")
    r = client.post("/api/v1/auth/register",
                    json={"email": email, "username": email.split("@")[0].replace(".", ""),
                          "password": "super-secret-1"})
    if r.status_code == 201:
        uid = r.json()["user"]["id"]
        with client.app.state.db.session() as session:
            session.get(User, uid).role = "admin"
            session.commit()


def test_fleet_settings_get_patch(client):
    _login_admin(client, "fleet2@example.com")
    r = client.get("/api/v1/admin/gpu-fleet/settings")
    assert r.status_code == 200
    assert r.json()["settings"]["swappiness"] == 50
    r = client.patch("/api/v1/admin/gpu-fleet/settings", json={"swappiness": 75})
    assert r.status_code == 200
    assert r.json()["settings"]["swappiness"] == 75
    assert client.get("/api/v1/admin/gpu-fleet/settings").json()["settings"]["swappiness"] == 75
    bad = client.patch("/api/v1/admin/gpu-fleet/settings", json={"swappiness": 150})
    assert bad.status_code == 422
    bad2 = client.patch("/api/v1/admin/gpu-fleet/settings", json={"nope": 1})
    assert bad2.status_code == 422


def test_fleet_offers_endpoint_mocked(client, monkeypatch):
    import requests

    _login_admin(client, "fleet3@example.com")

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"matches": [_raw("a"), _raw("b", dph_total=0.15), _raw("c", dph_total=0.99)]}

    calls = []
    monkeypatch.setattr(requests, "post", lambda url, json=None, headers=None, timeout=None: calls.append(url) or Resp())
    import app.routes.admin as adm
    adm._OFFER_CACHE.update({"key": None, "at": 0.0, "result": None})
    r = client.get("/api/v1/admin/gpu-fleet/offers")
    assert r.status_code == 200
    data = r.json()
    assert len(data["offers"]) == 2  # c excluded by price ceiling
    assert data["excluded"].get("PRICE_ABOVE_CEILING") == 1
    assert data["cached"] is False
    r2 = client.get("/api/v1/admin/gpu-fleet/offers")
    assert r2.json()["cached"] is True  # 30 s server cache
    assert len(calls) == 1
    # §19.30 provider failure surfaces as 502
    def boom(url, json=None, headers=None, timeout=None):
        raise RuntimeError("provider down")
    monkeypatch.setattr(requests, "post", boom)
    adm._OFFER_CACHE.update({"key": None, "at": 0.0, "result": None})
    assert client.get("/api/v1/admin/gpu-fleet/offers").status_code == 502


# ------------------------------------------------------- M3: deployments API

def _login_admin3(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    r = client.post("/api/v1/auth/register",
                    json={"email": "fleet4@example.com", "username": "fleet4", "password": "super-secret-1"})
    if r.status_code == 201:
        with client.app.state.db.session() as session:
            session.get(User, r.json()["user"]["id"]).role = "admin"
            session.commit()


def test_manual_deployment_idempotent_and_audited(client):
    """§19.34/35/40: manual deploy works while auto burst is on, double-submit
    collapses on the idempotency key, and an audit event is written."""
    from app.models import GpuFleetEvent

    _login_admin3(client)
    body = {"purpose": "xl-turbo", "idempotency_key": "deploy-abc"}
    r = client.post("/api/v1/admin/gpu-fleet/deployments", json=body)
    assert r.status_code == 201
    assert r.json()["created"] is True
    assert r.json()["deployment"]["origin"] == "MANUAL_ADMIN"
    assert r.json()["deployment"]["automatic_shutdown"] is False
    r2 = client.post("/api/v1/admin/gpu-fleet/deployments", json=body)
    assert r2.status_code == 200 and r2.json()["created"] is False  # §19.35
    with client.app.state.db.session() as session:
        from sqlalchemy import select as sa_select

        evs = session.execute(sa_select(GpuFleetEvent)
                              .where(GpuFleetEvent.action == "deploy_requested")).scalars().all()
    assert len(evs) == 1  # §19.40 (one event, not two)


def test_deployment_budget_enforced(client, monkeypatch):
    """§19.39: manual provisioning cannot silently bypass the daily budget."""
    from app.models import VastInstance

    _login_admin3(client)
    with client.app.state.db.session() as session:
        session.add(VastInstance(vast_instance_id="budget-1", hostname="budget-node",
                                 dph=0.25, state="running"))
        session.commit()
    monkeypatch.setattr("app.routes.admin._fleet_settings",
                        lambda request: {**_fset(), "daily_burst_budget_usd": 0.10})
    r = client.post("/api/v1/admin/gpu-fleet/deployments",
                    json={"purpose": "auto", "idempotency_key": "deploy-budget"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BUDGET_EXHAUSTED"
    with client.app.state.db.session() as session:
        from sqlalchemy import delete as sa_delete

        session.execute(sa_delete(VastInstance).where(VastInstance.vast_instance_id == "budget-1"))
        session.commit()


def test_worker_stop_busy_guard(client, monkeypatch):
    """§19.36: stop during active generation needs force."""
    from app.models import JobAttempt, VastInstance

    _login_admin3(client)
    monkeypatch.setattr("app.routes.admin._vast_request", lambda *a, **k: {})
    with client.app.state.db.session() as session:
        inst = VastInstance(vast_instance_id="busy-1", hostname="gpu-node-7", dph=0.2, state="running")
        session.add(inst)
        session.commit()
        iid = inst.id
    # no running attempt -> stop ok
    r = client.post("/api/v1/admin/gpu-fleet/workers/acestep-gpu-node-7-999/stop")
    assert r.status_code == 200
    # add a running attempt -> 409 unless force
    with client.app.state.db.session() as session:
        session.add(JobAttempt(job_id="x", attempt_number=1, worker_id="acestep-gpu-node-7-999",
                               status="running", lease_token="t"))
        session.commit()
    r = client.post("/api/v1/admin/gpu-fleet/workers/acestep-gpu-node-7-999/stop")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "WORKER_BUSY"
    r = client.post("/api/v1/admin/gpu-fleet/workers/acestep-gpu-node-7-999/stop?force=true")
    assert r.status_code == 200
    with client.app.state.db.session() as session:
        from sqlalchemy import delete as sa_delete, select as sa_select

        session.execute(sa_delete(JobAttempt).where(JobAttempt.lease_token == "t"))
        rec = session.execute(sa_select(VastInstance).where(VastInstance.id == iid)).scalars().first()
        if rec:
            session.delete(rec)
        session.commit()


def test_manual_contracts_protected_from_scaledown():
    """§19.38: routine scale-down must not destroy manual workers."""
    import importlib.util, pathlib

    root = pathlib.Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("autoscale_m3", root / "scripts" / "autoscale.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # no DB -> empty set (best-effort), and the tick filter uses it
    assert mod.manual_contracts() == set()


def test_nonadmin_denied(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    r = client.post("/api/v1/auth/register",
                    json={"email": "pleb@example.com", "username": "pleb", "password": "super-secret-1"})
    assert r.status_code == 201
    resp = client.get("/api/v1/admin/gpu-fleet")
    assert resp.status_code == 403  # §19.32
    with client.app.state.db.session() as session:
        session.get(User, r.json()["user"]["id"])
    client.post("/api/v1/auth/logout")


# ------------------------------------------------- §19 completion (tests 21-40)

def test_peek_window_uses_configured_size(client, orch, monkeypatch) -> None:
    """§19.7: the scan window is bounded by scheduler_peek_window."""
    monkeypatch.setattr(orch.settings, "scheduler_peek_window", 7)
    _submit(client, orch, "w1-t1", "turbo")
    orch.dispatcher.publish_once()
    seen: list[int] = []
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(1)), FakeEngineProcess(TURBO)))
    real_peek = orch.queue.peek
    monkeypatch.setattr(orch.queue, "peek",
                        lambda q, n: seen.append(n) or real_peek(q, n))
    assert worker.run_once() is True
    assert seen and all(n == 7 for n in seen)


def test_brpop_fallback_when_peek_empty(client, orch, monkeypatch) -> None:
    """§19.7b: if the peek path finds nothing the worker still BRPOP-consumes."""
    _submit(client, orch, "w2-t1", "turbo")
    orch.dispatcher.publish_once()
    monkeypatch.setattr(orch.queue, "peek", lambda q, n: [])
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(1)), FakeEngineProcess(TURBO)))
    assert worker.run_once() is True
    assert _status(client, orch, "w2-t1") == "succeeded"


def test_claim_removes_exactly_one_hint(client, orch) -> None:
    """§19.8b: LREM removes one occurrence, never the whole queue."""
    _submit(client, orch, "w3-t1", "turbo")
    _submit(client, orch, "w3-t2", "turbo")
    orch.dispatcher.publish_once()
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(1)), FakeEngineProcess(TURBO)))
    assert worker.run_once() is True
    assert orch.queue.depth("oal:queue:ace-step-1.5") == 1


def test_loaded_model_reported_on_worker_row(client, orch) -> None:
    """§19.11: workers.loaded_model reflects the resident checkpoint family."""
    from app.models import Worker

    _submit(client, orch, "w4-t1", "turbo")
    orch.dispatcher.publish_once()
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(1)), FakeEngineProcess(TURBO)))
    assert worker.run_once() is True
    worker.register()
    with orch.db.session() as session:
        row = session.execute(select(Worker).where(Worker.id == "test-smqm")).scalar_one()
    assert row.loaded_model == TURBO


def test_priority_aging_forces_switch(client, orch, monkeypatch) -> None:
    """§19.4b: an over-aged other-model job goes next even with work loaded."""
    monkeypatch.setattr(orch.settings, "max_model_queue_wait_seconds", 0)
    monkeypatch.setattr(orch.settings, "priority_aging_enabled", True)
    _submit(client, orch, "w5-xl", "xl")
    _submit(client, orch, "w5-t1", "turbo")
    orch.dispatcher.publish_once()
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(1)), FakeEngineProcess(TURBO)))
    assert worker.run_once() is True
    assert _status(client, orch, "w5-xl") == "succeeded"


def test_priority_aging_disabled_keeps_affinity(client, orch, monkeypatch) -> None:
    """§19.4c: with aging off, loaded-model affinity still wins."""
    monkeypatch.setattr(orch.settings, "max_model_queue_wait_seconds", 0)
    monkeypatch.setattr(orch.settings, "priority_aging_enabled", False)
    _submit(client, orch, "w6-xl", "xl")
    _submit(client, orch, "w6-t1", "turbo")
    orch.dispatcher.publish_once()
    worker = _always_runnable(_worker(orch, FakeAdapter(_outcomes(1)), FakeEngineProcess(TURBO)))
    assert worker.run_once() is True
    assert _status(client, orch, "w6-t1") == "succeeded"
    assert _status(client, orch, "w6-xl") == "queued"


def test_offer_normalize_maps_fields(client) -> None:
    """§19.13: provider payload normalization (bytes->GB, geolocation split)."""
    from app import vast_offers as vo

    o = vo.normalize(_raw())
    assert o["offer_id"] == "o1" and o["vram_gb"] == 24
    assert o["country"] == "US" and o["region"] == "Los Angeles, US"
    assert o["dph"] == 0.20 and o["disk_gb"] == 150.0


def test_offer_normalize_bundles_units(client) -> None:
    """§19.13b: bundles API reports gpu_ram in MB and compute_cap x100."""
    from app import vast_offers as vo

    o = vo.normalize(_raw(gpu_ram=24576, compute_cap=1200, inet_down=0.0))
    assert o["vram_gb"] == 24.0 and o["compute_cap"] == 12.0
    assert o["download_mbps"] is None  # 0.0 placeholder -> Not reported
    # bundles returns verified=null; the server-side filter enforces it
    assert vo.ineligible_reason(o, vo.criteria_defaults()) is None


def test_offer_checkpoint_size_affects_readiness(client) -> None:
    """§19.14: bigger checkpoints take longer; family map is explicit."""
    from app import vast_offers as vo

    assert vo.CHECKPOINT_GB == {"turbo": 5.0, "sft": 5.0, "xl": 9.0, "merge": 9.0}
    o = vo.normalize(_raw())
    assert vo.est_ready_seconds(o, vo.CHECKPOINT_GB["xl"]) > vo.est_ready_seconds(o, vo.CHECKPOINT_GB["turbo"])


def test_offer_score_deterministic_and_cost_aware(client) -> None:
    """§19.15: ranking is reproducible and prefers cheaper eligible offers."""
    from app import vast_offers as vo

    crit = vo.criteria_defaults()
    cheap = vo.normalize(_raw("cheap", dph_total=0.10))
    pricey = vo.normalize(_raw("pricey", dph_total=0.24))
    assert vo.score(cheap, crit) == vo.score(cheap, crit)
    assert vo.score(cheap, crit) > vo.score(pricey, crit)


def test_offer_weights_sum_to_one(client) -> None:
    """§19.16: the documented ranking weights are complete."""
    from app import vast_offers as vo

    assert abs(sum(vo.DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


def test_offer_search_offers_pipeline(client) -> None:
    """§19.17: search_offers = fetch -> filter -> rank in one call."""
    from app import vast_offers as vo

    raws = [_raw("ok1"), _raw("ok2", dph_total=0.12), _raw("bad", dph_total=0.99)]
    res = vo.rank(vo.search_offers(lambda crit: raws), limit=10)
    assert [o["offer_id"] for o in res["offers"]] == ["ok2", "ok1"]
    assert res["excluded"]["PRICE_ABOVE_CEILING"] == 1


def test_settings_validate_bounds(client) -> None:
    """§19.31: swappiness outside 0-100 is rejected."""
    from app.fleet_settings import FleetSettingsError, validate

    for bad in (125, -5):
        try:
            validate({"swappiness": bad})
            raise AssertionError(f"swappiness={bad} accepted")
        except FleetSettingsError:
            pass
    assert validate({"swappiness": 75})["swappiness"] == 75


def test_settings_validate_unknown_key(client) -> None:
    """§19.31b: unknown keys fail closed (no silent typos)."""
    from app.fleet_settings import FleetSettingsError, validate

    try:
        validate({"swinesness": 50})
        raise AssertionError("unknown key accepted")
    except FleetSettingsError:
        pass


def test_settings_patch_invalid_400(client) -> None:
    """§19.31c: the API surfaces validation failures as 400."""
    _login_admin(client, "fleet5@example.com")
    r = client.patch("/api/v1/admin/gpu-fleet/settings", json={"swappiness": 250})
    assert r.status_code == 422
    assert client.get("/api/v1/admin/gpu-fleet/settings").json()["settings"]["swappiness"] != 250


def test_deployment_offer_revalidation_409(client, monkeypatch) -> None:
    """§19.28b: deploy-time revalidation blocks changed/unavailable offers."""
    _login_admin3(client)

    import requests as _rq

    class Resp:
        def __init__(self, body):
            self._b = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._b

    def fake_post(url, json=None, headers=None, timeout=None):
        oid = json["ask_contract_id"]["eq"]
        if oid == 404:
            return Resp({"offers": []})
        return Resp({"offers": [_raw(str(oid), dph_total=0.42)]})

    monkeypatch.setattr(_rq, "post", fake_post)
    r = client.post("/api/v1/admin/gpu-fleet/deployments",
                    json={"offer_id": 404, "idempotency_key": "dep-404"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "OFFER_UNAVAILABLE"
    r = client.post("/api/v1/admin/gpu-fleet/deployments",
                    json={"offer_id": 7, "idempotency_key": "dep-7"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "OFFER_CHANGED"


def test_deployment_detail_and_404(client) -> None:
    """§19.33: deployment tracking by id; unknown ids are 404."""
    _login_admin3(client)
    r = client.post("/api/v1/admin/gpu-fleet/deployments", json={"idempotency_key": "dep-detail"})
    did = r.json()["deployment"]["id"]
    assert client.get(f"/api/v1/admin/gpu-fleet/deployments/{did}").status_code == 200
    assert client.get("/api/v1/admin/gpu-fleet/deployments/nope").status_code == 404


def test_worker_destroy_and_restart(client, monkeypatch) -> None:
    """§19.36b: destroy/restart lifecycle calls the provider."""
    from app.models import VastInstance

    _login_admin3(client)
    calls: list[tuple] = []
    monkeypatch.setattr("app.routes.admin._vast_request",
                        lambda request, method, path, body=None: calls.append((method, path, body)) or {})
    with client.app.state.db.session() as session:
        session.add(VastInstance(vast_instance_id="dc-1", hostname="gpu-node-8", dph=0.2, state="running"))
        session.commit()
    assert client.post("/api/v1/admin/gpu-fleet/workers/acestep-gpu-node-8-999/restart").status_code == 200
    assert client.delete("/api/v1/admin/gpu-fleet/workers/acestep-gpu-node-8-999").status_code == 200
    assert any((body or {}).get("action_type") == "destroy" for _, _, body in calls)


def test_costs_endpoint_shape(client) -> None:
    """§19.37: costs expose today, categories and running instances."""
    _login_admin3(client)
    r = client.get("/api/v1/admin/gpu-fleet/costs")
    assert r.status_code == 200
    data = r.json()
    assert "today_usd" in data and "categories_usd" in data and "running" in data


def test_events_endpoint_shape(client) -> None:
    """§19.40b: events expose both the audit trail and swappiness decisions."""
    _login_admin3(client)
    r = client.get("/api/v1/admin/gpu-fleet/events")
    assert r.status_code == 200
    assert "events" in r.json() and "decisions" in r.json()


def test_overview_endpoint_shape(client) -> None:
    """§19.32b: fleet overview aggregates workers, deployments and spend."""
    _login_admin3(client)
    r = client.get("/api/v1/admin/gpu-fleet")
    assert r.status_code == 200
    for key in ("workers", "ready", "active_deployments", "spend_today_usd"):
        assert key in r.json()
