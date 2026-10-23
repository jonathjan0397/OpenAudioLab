"""T-A/T-B: bundle base enforcement at admission + cross-checkpoint compat probes."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

_SEQ = iter(range(1, 10000))


def test_bundle_base_family_rule() -> None:
    from app.model_lab_release import bundle_base_compatible

    assert bundle_base_compatible("acestep-v15-turbo", "acestep-v15-sft")
    assert bundle_base_compatible("acestep-v15-xl-sft", "acestep-v15-xl-turbo")
    assert not bundle_base_compatible("acestep-v15-turbo", "acestep-v15-xl-turbo")
    assert bundle_base_compatible(None, "acestep-v15-xl-turbo")  # unknown base: permissive


@pytest.fixture(autouse=True)
def _admin(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    resp = client.post("/api/v1/auth/register",
                       json={"email": f"ct{next(_SEQ)}@example.com",
                             "username": f"ct{next(_SEQ)}", "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def _released_bundle(client, *, base="acestep-v15-turbo", state="released"):
    from app.models import MlModelBundle, new_uuid

    key = f"ml/adapters/att-ct-{next(_SEQ)}/model.safetensors"
    body = b"peft-bytes"
    client.app.state.storage.put(key, body)
    bid = new_uuid()
    with client.app.state.db.session() as session:
        session.add(MlModelBundle(id=bid, name=f"ct-b{next(_SEQ)}", version="v1",
                                  kind="adapter", base_model=base, state=state,
                                  artifact_key=key,
                                  sha256=hashlib.sha256(body).hexdigest(),
                                  bundle_json={"acceptance": {"lora_load": True},
                                              "evaluations": [{"kind": "ab",
                                                               "verdict": "pass"}]}))
        session.commit()
    return bid


def test_admission_blocks_cross_family_bundle(client) -> None:
    from conftest import submit_body

    headers = {"Authorization": "Bearer user-a-secret-token"}
    good = _released_bundle(client)
    r = client.post("/api/v1/jobs", headers={**headers, "Idempotency-Key": f"ct-{next(_SEQ)}"},
                    json=submit_body(bundle_id=good))
    assert r.status_code == 202, r.text
    xl = _released_bundle(client, base="acestep-v15-xl-turbo")
    bad = client.post("/api/v1/jobs", headers={**headers, "Idempotency-Key": f"ct-{next(_SEQ)}"},
                      json=submit_body(bundle_id=xl))
    assert bad.status_code == 409
    assert bad.json()["error"]["code"] == "BUNDLE_BASE_MISMATCH"


def test_materialize_bundle_uses_peft_naming(client, tmp_path) -> None:
    from app.engine_worker import EngineWorker

    client.app.state.settings.adapter_cache_dir = str(tmp_path / "adapter-cache")
    bid = _released_bundle(client)
    with client.app.state.db.session() as session:
        from app.models import MlModelBundle
        b = session.get(MlModelBundle, bid)
        key = b.artifact_key
    cfg = key.rsplit("/", 1)[0] + "/adapter_config.json"
    client.app.state.storage.put(cfg, b'{"peft_type": "LORA"}')
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings)
    path = EngineWorker._materialize_bundle(w, bid)
    assert path
    files = sorted(p.name for p in __import__("pathlib").Path(path).iterdir())
    assert files == ["adapter_config.json", "adapter_model.safetensors"]
    assert EngineWorker._materialize_bundle(w, None) is None


def _fake_engine(tw_module, monkeypatch, target_ok=True):
    class _A:
        def __init__(self):
            self.models = []

        def ensure_model(self, model=None):
            self.models.append(model)
            if model and "missing" in model:
                raise tw_module.EngineError("ENGINE_FAIL", "no such checkpoint")

        def load_lora(self, path, name=None):
            self.models.append(f"load:{name}")

        def unload_lora(self):
            self.models.append("unload")

    class _Gen:
        last_error = ""

        def build_payload(self, **kw):
            return dict(kw)

        def submit(self, payload):
            return SimpleNamespace(task_id="t-1")

        def poll(self, task_id):
            return "succeeded", [{"file": "/v1/audio?path=/x/1.mp3"}]

        def download(self, url):
            return b"compat-audio" * 200
    return _A(), _Gen()


def test_compat_probe_flow(client, tmp_path, monkeypatch) -> None:
    import app.training_worker as tw
    from app.orchestration import claim_attempt

    client.app.state.settings.train_workdir = str(tmp_path / "work")
    client.app.state.settings.review_dir = str(tmp_path / "review")
    bid = _released_bundle(client)
    r = client.post(f"/api/v1/admin/model-lab/bundles/{bid}/compat-probe",
                    json={"target_model": "acestep-v15-sft",
                          "prompts": [{"name": "probe1", "caption": "bright pop",
                                       "instrumental": True}]})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    _, att, lease = claim_attempt(client.app.state.db, job_id, "w-ct")
    a, gen = _fake_engine(tw, monkeypatch)
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings, worker_id="w-ct",
                        adapter=a, gen_adapter=gen)
    w._lease_beat = lambda *args: tw.TrainingWorker._lease_beat(w, *args)
    tw.TrainingWorker._model_lab_compat(w, job_id, att, lease)
    assert "acestep-v15-sft" in a.models
    assert any(m.startswith("load:compat-") for m in a.models)
    with client.app.state.db.session() as session:
        from app.models import MlModelBundle
        b = session.get(MlModelBundle, bid)
        assert b.bundle_json["compat"]["acestep-v15-sft"] == "rendered_pending_review"
    dest = tmp_path / "review" / bid
    assert (dest / "compat-acestep-v15-sft-native-probe1.mp3").is_file()
    assert (dest / "compat-acestep-v15-sft-adapted-probe1.mp3").is_file()
    assert (dest / "index.html").is_file()
    page = (dest / "index.html").read_text()
    assert "compat-acestep-v15-sft-native-probe1.mp3" in page
    assert "compat-acestep-v15-sft-adapted-probe1.mp3" in page


def test_compat_stamp_verdicts(client) -> None:
    bid = _released_bundle(client)
    r = client.post(f"/api/v1/admin/model-lab/bundles/{bid}/compat",
                    json={"target_model": "acestep-v15-sft", "verdict": "verified"})
    assert r.status_code == 200
    assert r.json()["compat"]["acestep-v15-sft"] == "verified"
    bad = client.post(f"/api/v1/admin/model-lab/bundles/{bid}/compat",
                      json={"target_model": "x", "verdict": "maybe"})
    assert bad.status_code == 422
    listing = client.get("/api/v1/admin/model-lab/bundles").json()["bundles"]
    row = next(b for b in listing if b["id"] == bid)
    assert row["compat"]["acestep-v15-sft"] == "verified"
    assert row["base_model"] == "acestep-v15-turbo"
