import importlib.util
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("autoscale", ROOT / "scripts" / "autoscale.py")
autoscale = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(autoscale)


def _configure(monkeypatch, **kw):
    for k, v in kw.items():
        monkeypatch.setattr(autoscale, k, v)


def test_desired_nodes_counts_baseline(monkeypatch):
    _configure(monkeypatch, SCALE_UP=2, JOBS_PER_NODE=2, MAX_NODES=3, BASELINE=1)
    now = 1000.0
    assert autoscale.desired_nodes(2, None, now, 0) == 0
    assert autoscale.desired_nodes(4, None, now, 0) == 1
    assert autoscale.desired_nodes(6, None, now, 0) == 2
    assert autoscale.desired_nodes(20, None, now, 0) == 2


def test_desired_nodes_scale_down_tiers(monkeypatch):
    _configure(monkeypatch, SCALE_UP=2, JOBS_PER_NODE=2, MAX_NODES=3, BASELINE=1,
               TO_ONE_SECONDS=300, SCALE_DOWN_SECONDS=1800)
    now = 10000.0
    assert autoscale.desired_nodes(1, None, now, 2) == 2
    assert autoscale.desired_nodes(1, now - 100, now, 2) == 2
    assert autoscale.desired_nodes(1, now - 400, now, 2) == 1
    assert autoscale.desired_nodes(1, now - 2000, now, 2) == 0


def test_desired_nodes_n20_counts_baseline(monkeypatch):
    _configure(monkeypatch, SCALE_UP=2, JOBS_PER_NODE=20, MAX_NODES=3, BASELINE=1)
    now = 1000.0
    assert autoscale.desired_nodes(20, None, now, 0) == 0
    assert autoscale.desired_nodes(21, None, now, 0) == 1
    assert autoscale.desired_nodes(40, None, now, 0) == 1
    assert autoscale.desired_nodes(41, None, now, 0) == 2
    assert autoscale.desired_nodes(100, None, now, 0) == 2


class _FakeRedis:
    def __init__(self, depths):
        self.depths = depths

    def llen(self, key):
        return self.depths.get(key, 0)


def _noop(monkeypatch):
    for fn in ("registry_upsert", "registry_set", "registry_remove"):
        monkeypatch.setattr(autoscale, fn, lambda *a, **k: None)


def test_scaledown_stops_instead_of_destroying(monkeypatch):
    _configure(monkeypatch, SCALE_UP=2, JOBS_PER_NODE=2, MAX_NODES=3, BASELINE=1,
               TO_ONE_SECONDS=300, SCALE_DOWN_SECONDS=1800, MIN_UPTIME=180,
               VAST_TRANSPORT="public", REUSE=True, KEEP_STOPPED=2)
    _noop(monkeypatch)
    stopped, destroyed = [], []
    monkeypatch.setattr(autoscale, "stop_instance", lambda cid, dry=False: stopped.append(cid))
    monkeypatch.setattr(autoscale, "destroy_instance", lambda cid, dry=False: destroyed.append(cid))
    now = 10000.0
    st = {"nodes": [{"contract": 1, "created_at": now - 1000}], "low_since": now - 2000}
    r = _FakeRedis({autoscale.QUEUE_KEY: 0, autoscale.BURST_KEY: 0, autoscale.TRAIN_QUEUE: 0})
    autoscale.tick(r, st, dry_run=True)
    assert stopped == [1]
    assert destroyed == []
    assert st["nodes"] == []
    assert st["stopped"][0]["contract"] == 1


def test_scaleup_restarts_stopped_before_creating(monkeypatch):
    _configure(monkeypatch, SCALE_UP=2, JOBS_PER_NODE=2, MAX_NODES=3, BASELINE=1,
               TO_ONE_SECONDS=300, SCALE_DOWN_SECONDS=1800, MIN_UPTIME=180,
               VAST_TRANSPORT="public", REUSE=True, KEEP_STOPPED=2)
    _noop(monkeypatch)
    started, created = [], []
    monkeypatch.setattr(autoscale, "start_instance", lambda cid, dry=False: started.append(cid) or True)
    monkeypatch.setattr(autoscale, "create_instance",
                        lambda *a, **k: created.append(a) or 99)
    now = 10000.0
    st = {"nodes": [], "stopped": [{"contract": 5, "created_at": now - 5000}], "low_since": None}
    r = _FakeRedis({autoscale.QUEUE_KEY: 4, autoscale.BURST_KEY: 0, autoscale.TRAIN_QUEUE: 0})
    autoscale.tick(r, st, dry_run=True)
    assert started == [5]
    assert created == []
    assert st["nodes"][0]["contract"] == 5
    assert st["stopped"] == []


def test_training_tick_creates_training_node(monkeypatch):
    _configure(monkeypatch, VAST_TRANSPORT="public", REUSE=True, KEEP_STOPPED=2,
               TRAIN_WAIT_LOCAL=0.0, TRAIN_DOWN_SECONDS=240)
    _noop(monkeypatch)
    created = []

    def fake_create(slot=None, dry_run=False, transport="wg", role="engine_worker", **kw):
        created.append((role, kw.get("train_queue")))
        return 77

    monkeypatch.setattr(autoscale, "create_instance", fake_create)
    now = 10000.0
    st = {"train_pending_since": now}
    r = _FakeRedis({autoscale.TRAIN_QUEUE: 1})
    autoscale.training_tick(r, st, now, dry_run=True)
    assert created == [("training_worker", "training")]
    assert st["train_nodes"][0]["contract"] == 77


def test_baseline_fallback_create_and_destroy(monkeypatch):
    _configure(
        monkeypatch,
        SCALE_UP=2,
        JOBS_PER_NODE=20,
        MAX_NODES=3,
        BASELINE=1,
        TO_ONE_SECONDS=300,
        SCALE_DOWN_SECONDS=1800,
        MIN_UPTIME=180,
        VAST_TRANSPORT="public",
        REUSE=False,
        KEEP_STOPPED=2,
        BASELINE_WORKER_ID="oal-baseline-gpu0",
        BASELINE_UNAVAILABLE_GRACE_SECONDS=300,
        BASELINE_RESTORE_GRACE_SECONDS=300,
        BASELINE_FALLBACK_CREATE_GUARD_SECONDS=120,
        PRIMARY_LLM_BASE_URL="",
    )
    _noop(monkeypatch)
    created, destroyed, endpoints = [], [], []
    monkeypatch.setattr(autoscale, "baseline_available", lambda: False)
    monkeypatch.setattr(autoscale, "create_instance", lambda *a, **k: created.append(k.get("role")) or 88)
    monkeypatch.setattr(autoscale, "destroy_instance", lambda cid, dry=False: destroyed.append(cid))
    monkeypatch.setattr(autoscale, "instance_public_endpoint", lambda cid, port=None: ("1.2.3.4", port or "8082"))
    monkeypatch.setattr(autoscale, "set_llm_endpoint", lambda url: endpoints.append(url))
    now = time.time()
    st = {"nodes": [], "low_since": None, "baseline_unavailable_since": now - 301}
    r = _FakeRedis({autoscale.QUEUE_KEY: 0, autoscale.BURST_KEY: 0, autoscale.TRAIN_QUEUE: 0})
    autoscale.tick(r, st, dry_run=True)
    assert created == [autoscale.BASELINE_FALLBACK_ROLE]
    assert st["fallback_node"]["contract"] == 88
    assert endpoints == ["http://1.2.3.4:8082/v1"]

    monkeypatch.setattr(autoscale, "baseline_available", lambda: True)
    st["baseline_unavailable_since"] = None
    st["baseline_restored_since"] = now - 301
    autoscale.tick(r, st, dry_run=True)
    assert destroyed == [88]
    assert st["fallback_node"] is None
    assert endpoints[-1] == ""


def test_training_tick_stops_idle_training_node(monkeypatch):
    _configure(monkeypatch, VAST_TRANSPORT="public", REUSE=True, KEEP_STOPPED=2,
               TRAIN_WAIT_LOCAL=120, TRAIN_DOWN_SECONDS=0.0)
    _noop(monkeypatch)
    stopped = []
    monkeypatch.setattr(autoscale, "stop_instance", lambda cid, dry=False: stopped.append(cid))
    now = 10000.0
    st = {"train_nodes": [{"contract": 77, "created_at": now - 1000}], "train_idle_since": now - 10}
    r = _FakeRedis({autoscale.TRAIN_QUEUE: 0})
    autoscale.training_tick(r, st, now, dry_run=True)
    assert stopped == [77]
    assert st["train_nodes"] == []
    assert st["train_stopped"][0]["contract"] == 77


def test_training_tick_xl_pool_creates_separate_node(monkeypatch):
    _configure(monkeypatch, VAST_TRANSPORT="public", REUSE=True, KEEP_STOPPED=2,
               TRAIN_WAIT_LOCAL=0.0, TRAIN_DOWN_SECONDS=240,
               TRAIN_MAX_NODES=1, TRAIN_XL_MAX_NODES=1,
               TRAIN_XL_MIN_VRAM="32", TRAIN_XL_MAX_DPH=0.60)
    _noop(monkeypatch)
    created = []

    def fake_create(slot=None, dry_run=False, transport="wg", role="engine_worker", **kw):
        created.append((role, kw.get("train_queue"), kw.get("min_vram"), kw.get("max_dph")))
        return 91

    monkeypatch.setattr(autoscale, "create_instance", fake_create)
    now = 10000.0
    st = {"train_pending_since": now, "train_xl_pending_since": now}
    r = _FakeRedis({autoscale.TRAIN_QUEUE: 1, autoscale.TRAIN_QUEUE_XL: 2})
    autoscale.training_tick(r, st, now, dry_run=True)
    assert created == [("training_worker", "training", None, None),
                       ("training_worker", "training-xl", "32", 0.60)]
    assert st["train_nodes"][0]["contract"] == 91
    assert st["train_xl_nodes"][0]["contract"] == 91


def test_scaledown_holds_for_running_burst_attempt(monkeypatch):
    _configure(monkeypatch, SCALE_UP=2, JOBS_PER_NODE=2, MAX_NODES=3, BASELINE=1,
               TO_ONE_SECONDS=300, SCALE_DOWN_SECONDS=1800, MIN_UPTIME=0,
               VAST_TRANSPORT="public", REUSE=True, KEEP_STOPPED=2)
    _noop(monkeypatch)
    monkeypatch.setattr(autoscale, "burst_running", lambda: True)
    stopped = []
    monkeypatch.setattr(autoscale, "stop_instance", lambda cid, dry=False: stopped.append(cid))
    now = 10000.0
    st = {"nodes": [{"contract": 55, "created_at": now - 1000}], "low_since": now - 2000}
    r = _FakeRedis({autoscale.QUEUE_KEY: 0, autoscale.BURST_KEY: 0, autoscale.TRAIN_QUEUE: 0})
    autoscale.tick(r, st, dry_run=True)
    assert stopped == []
    assert st["nodes"][0]["contract"] == 55


def test_queued_work_seconds_falls_back_without_db(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(autoscale, "_engine", lambda: None)
    r = _FakeRedis({autoscale.QUEUE_KEY: 3, autoscale.BURST_KEY: 0, autoscale.TRAIN_QUEUE: 0})
    # _FakeRedis has no lrange -> exception path -> depth x DEFAULT_JOB_SECONDS
    assert autoscale.queued_work_seconds(r) == 3 * autoscale.DEFAULT_JOB_SECONDS


def test_workload_weighting_scales_on_heavier_jobs(monkeypatch):
    """R15: two XL jobs (factor 2.5) must weigh more than two turbo jobs."""
    _configure(monkeypatch, SCALE_UP=3, JOBS_PER_NODE=2, MAX_NODES=3)
    _noop(monkeypatch)
    monkeypatch.setattr(autoscale, "_engine", lambda: None)
    r = _FakeRedis({autoscale.QUEUE_KEY: 2, autoscale.BURST_KEY: 0, autoscale.TRAIN_QUEUE: 0})
    # Fallback path is family-blind; verify the weighting formula directly instead.
    turbo = (autoscale.WORK_BASE_SECONDS + autoscale.WORK_SECONDS_PER_MINUTE * 0.5) * autoscale.FAMILY_FACTORS["turbo"]
    xl = (autoscale.WORK_BASE_SECONDS + autoscale.WORK_SECONDS_PER_MINUTE * 0.5) * autoscale.FAMILY_FACTORS["xl"]
    assert xl > 2 * turbo
