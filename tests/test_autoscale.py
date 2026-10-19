import importlib.util
import pathlib

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

    def fake_create(slot=None, dry_run=False, transport="wg", role="engine_worker"):
        created.append(role)
        return 77

    monkeypatch.setattr(autoscale, "create_instance", fake_create)
    now = 10000.0
    st = {"train_pending_since": now}
    r = _FakeRedis({autoscale.TRAIN_QUEUE: 1})
    autoscale.training_tick(r, st, now, dry_run=True)
    assert created == ["training_worker"]
    assert st["train_nodes"][0]["contract"] == 77


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
