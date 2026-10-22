"""Model Lab M5: merge recipe validation, merge execution, bundle lifecycle."""

from __future__ import annotations

import pytest

from app import model_lab_merge
from conftest import auth

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    email = f"ml5admin{next(_SEQ)}@example.com"
    resp = client.post("/api/v1/auth/register",
                       json={"email": email, "username": f"ml5a{next(_SEQ)}",
                             "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def _adapter(client, state="active"):
    from app.models import Lora, new_uuid

    with client.app.state.db.session() as session:
        a = Lora(id=f"m5-a{next(_SEQ)}", name=f"ad-{next(_SEQ)}", kind="genre", state=state)
        session.add(a)
        session.commit()
        return a.id


def test_recipe_validation(client) -> None:
    a, b = _adapter(client), _adapter(client)
    r = client.post("/api/v1/admin/model-lab/merge-recipes",
                    json={"name": "mix-1", "base_model": "ace-step-1.5",
                          "adapter_ids": [a, b], "method": "slerp"})
    assert r.status_code == 201
    bad_method = client.post("/api/v1/admin/model-lab/merge-recipes",
                             json={"name": "x", "base_model": "m", "adapter_ids": [a, b],
                                   "method": "magic"})
    assert bad_method.status_code == 422
    unknown = client.post("/api/v1/admin/model-lab/merge-recipes",
                          json={"name": "x", "base_model": "m", "adapter_ids": [a, "nope"],
                                "method": "dare"})
    assert unknown.status_code == 422
    not_ready = client.post("/api/v1/admin/model-lab/merge-recipes",
                            json={"name": "x", "base_model": "m",
                                  "adapter_ids": [a, _adapter(client, state="training")],
                                  "method": "dare"})
    assert not_ready.status_code == 422


def test_merge_unavailable_without_command(client) -> None:
    a, b = _adapter(client), _adapter(client)
    rid = client.post("/api/v1/admin/model-lab/merge-recipes",
                      json={"name": "mix-2", "base_model": "m", "adapter_ids": [a, b]}
                      ).json()["id"]
    r = client.post(f"/api/v1/admin/model-lab/merge-recipes/{rid}/run")
    assert r.status_code == 409 and r.json()["error"]["code"] == "MERGE_UNAVAILABLE"


def test_merge_run_creates_candidate_and_versions(client, monkeypatch) -> None:
    class Proc:
        returncode = 0
        stdout = 'noise\n{"sha256": "abcdef", "artifact_key": "ml/merge.safetensors"}'
        stderr = ""

    monkeypatch.setattr(model_lab_merge.subprocess, "run", lambda *a, **k: Proc())
    a, b = _adapter(client), _adapter(client)
    rid = client.post("/api/v1/admin/model-lab/merge-recipes",
                      json={"name": "mix-3", "base_model": "m", "adapter_ids": [a, b]}
                      ).json()["id"]
    client.app.state.settings.model_lab_merge_command = "echo merge"
    r1 = client.post(f"/api/v1/admin/model-lab/merge-recipes/{rid}/run")
    assert r1.status_code == 202 and r1.json()["version"] == "v1"
    assert r1.json()["state"] == "building" and r1.json()["job_id"]
    r2 = client.post(f"/api/v1/admin/model-lab/merge-recipes/{rid}/run")
    assert r2.json()["version"] == "v2"  # immutable versions, no overwrite


def test_bundle_lifecycle(client, monkeypatch) -> None:
    class Proc:
        returncode = 0
        stdout = '{"sha256": "cd"}'
        stderr = ""

    monkeypatch.setattr(model_lab_merge.subprocess, "run", lambda *a, **k: Proc())
    client.app.state.settings.model_lab_merge_command = "echo merge"
    a, b = _adapter(client), _adapter(client)
    rid = client.post("/api/v1/admin/model-lab/merge-recipes",
                      json={"name": "mix-4", "base_model": "m", "adapter_ids": [a, b]}
                      ).json()["id"]
    run = client.post(f"/api/v1/admin/model-lab/merge-recipes/{rid}/run")
    bid = run.json()["bundle"]
    assert run.json()["state"] == "building"
    building_retire = client.post(f"/api/v1/admin/model-lab/bundles/{bid}/retire")
    assert building_retire.status_code == 409  # building cannot retire
    with client.app.state.db.session() as session:
        from app.model_lab_merge import finish_merge_build
        from app.models import MlModelBundle
        finish_merge_build(session, session.get(MlModelBundle, bid),
                           ok=True, result={"sha256": "cd"})
    early_retire = client.post(f"/api/v1/admin/model-lab/bundles/{bid}/retire")
    assert early_retire.status_code == 409  # candidate cannot retire
    assert client.post(f"/api/v1/admin/model-lab/bundles/{bid}/release").json()["state"] == "released"
    double = client.post(f"/api/v1/admin/model-lab/bundles/{bid}/release")
    assert double.status_code == 409
    assert client.post(f"/api/v1/admin/model-lab/bundles/{bid}/retire").json()["state"] == "retired"
