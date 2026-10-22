"""M5: async identification, caption compiler, BYOL discovery gate."""

from __future__ import annotations

import pytest

_SEQ = iter(range(1, 10000))


@pytest.fixture(autouse=True)
def _admin_session(client):
    from app.models import User

    client.post("/api/v1/auth/logout")
    email = f"m5pipe{next(_SEQ)}@example.com"
    resp = client.post("/api/v1/auth/register",
                       json={"email": email, "username": f"m5p{next(_SEQ)}",
                             "password": "super-secret-1"})
    uid = resp.json()["user"]["id"]
    with client.app.state.db.session() as session:
        session.get(User, uid).role = "admin"
        session.commit()


def _recording(client, **over) -> str:
    from app.models import MlRecording, MlSource, new_uuid

    with client.app.state.db.session() as session:
        src = session.execute(
            __import__("sqlalchemy").select(MlSource)).scalars().first()
        if src is None:
            src = MlSource(id=new_uuid(), name=f"m5p-src-{next(_SEQ)}", status="approved")
            session.add(src)
            session.commit()
        rec = MlRecording(id=new_uuid(), source_id=src.id, path=f"/p/{next(_SEQ)}.mp3",
                          sha256=f"m5p-{next(_SEQ)}", duration_seconds=120.0,
                          review_status="approved", **over)
        session.add(rec)
        session.commit()
        return rec.id


def test_identify_is_async(client) -> None:
    rid = _recording(client)
    r = client.post(f"/api/v1/admin/model-lab/recordings/{rid}/identify")
    assert r.status_code == 202
    assert r.json()["identify_status"] == "queued" and r.json()["job_id"]


def test_identify_worker_operation(client, monkeypatch) -> None:
    from types import SimpleNamespace

    import app.model_lab as model_lab
    from app.models import Asset
    from app.orchestration import claim_attempt
    from app.training_worker import TrainingWorker

    rid = _recording(client)
    job_id = client.post(f"/api/v1/admin/model-lab/recordings/{rid}/identify"
                         ).json()["job_id"]
    monkeypatch.setattr(model_lab, "identify_recording",
                        lambda session, rec, settings, enrich=True: "matched")
    claimed = claim_attempt(client.app.state.db, job_id, "w-m5")
    assert claimed is not None
    _, att, lease = claimed
    w = SimpleNamespace(db=client.app.state.db, storage=client.app.state.storage,
                        settings=client.app.state.settings, worker_id="w-m5")
    TrainingWorker._model_lab_identify(w, job_id, att, lease)
    with client.app.state.db.session() as session:
        job = session.execute(__import__("sqlalchemy").select(__import__("app.models",
                              fromlist=["Job"]).Job).where(
                              __import__("app.models", fromlist=["Job"]).Job.id
                              == job_id)).scalar_one()
        assert job.status == "succeeded"
        asset = session.execute(__import__("sqlalchemy").select(Asset)
                                .where(Asset.job_id == job_id)).scalar_one()
        assert asset.role == "identify-status"


def test_caption_compiler_deterministic(client) -> None:
    from app.models import MlTagAssignment, MlTagTerm, new_uuid

    rid = _recording(client, artist="The Strings", title="North Wall", year=1998,
                     decade="1990s", vocal_status="vocal")
    with client.app.state.db.session() as session:
        term = MlTagTerm(id=f"mood.melancholy.{next(_SEQ)}", namespace="mood",
                         label="melancholy")
        session.add(term)
        session.commit()
        session.add(MlTagAssignment(id=new_uuid(), recording_id=rid,
                                    term_id=term.id, status="approved"))
        session.commit()
    cap = client.get(f"/api/v1/admin/model-lab/recordings/{rid}/caption").json()
    assert cap["fields"]["artist"] == "The Strings"
    assert cap["fields"]["vocals"] == "vocal"
    assert cap["tags"] == [{"lane": "mood", "term": "melancholy"}]
    again = client.get(f"/api/v1/admin/model-lab/recordings/{rid}/caption").json()
    assert again["text"] == cap["text"]  # deterministic, no LLM


def test_byol_gate_fails_closed_and_wires(client) -> None:
    from app.config import get_settings
    from app.model_lab_voice import VoiceLabError, embed_byol, resolve_identity_model

    settings = client.app.state.settings
    original = settings.voice_identity_challenger
    settings.voice_identity_challenger = "byol-v1"
    try:
        settings.byol_model_path = ""
        settings.byol_scan_command = ""
        with pytest.raises(VoiceLabError):
            resolve_identity_model(settings)
        settings.byol_model_path = "/opt/byol/byl-light.pt"
        settings.byol_scan_command = "echo"
        assert resolve_identity_model(settings) == "byol-v1"
        import subprocess

        real_run = subprocess.run

        class Proc:
            returncode = 0
            stdout = 'noise\n{"vector": [0.5, 1.5]}\n'
            stderr = ""

        monkey = __import__("unittest.mock", fromlist=["mock"])
        with monkey.patch("subprocess.run", lambda *a, **k: Proc()):
            assert embed_byol(settings, "/x.wav") == [0.5, 1.5]
        assert real_run is subprocess.run
    finally:
        settings.voice_identity_challenger = original
