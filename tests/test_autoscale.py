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
