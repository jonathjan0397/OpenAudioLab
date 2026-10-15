from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.models import Asset, Job, JobAttempt, JobEvent, OutboxRecord, utcnow
from app.orchestration import claim_attempt, complete_attempt
from app.maintenance import expire_once
from conftest import TOKEN_A, auth, submit


def _job_id(client, key="k1", **overrides) -> str:
    response = submit(client, key=key, **overrides)
    assert response.status_code == 202
    return response.json()["job_id"]


def _status(db, job_id: str) -> str:
    with db.session() as session:
        return session.execute(select(Job).where(Job.id == job_id)).scalar_one().status


def _run_pipeline(client, orch, key="k1", **overrides) -> str:
    job_id = _job_id(client, key=key, **overrides)
    orch.dispatcher.publish_once()
    orch.worker.run_once()
    return job_id


def test_submit_creates_outbox_and_queued_event(client, orch) -> None:
    job_id = _job_id(client)
    with orch.db.session() as session:
        outbox = session.execute(select(OutboxRecord).where(OutboxRecord.job_id == job_id)).scalar_one()
        assert outbox.published_at is None
        events = list(session.execute(select(JobEvent).where(JobEvent.job_id == job_id)).scalars())
    assert [event.event for event in events] == ["queued"]


def test_dispatcher_publishes_once_no_double_publish(client, orch) -> None:
    _job_id(client)
    assert orch.dispatcher.publish_once() == 1
    assert orch.queue.depth("oal:queue:ace-step-1.5") == 1
    assert orch.dispatcher.publish_once() == 0


def test_happy_path_pipeline(client, orch) -> None:
    job_id = _run_pipeline(client, orch)
    assert _status(orch.db, job_id) == "succeeded"

    detail = client.get(f"/api/v1/jobs/{job_id}", headers=auth(TOKEN_A)).json()
    assert detail["stage"] == "done"
    assert detail["progress"] == 1.0
    assert detail["progress_source"] == "fixture"

    artifacts = client.get(f"/api/v1/jobs/{job_id}/artifacts", headers=auth(TOKEN_A)).json()["artifacts"]
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact["role"] == "mix_wav"
    assert artifact["synthetic_test_audio"] is True
    assert artifact["mime"] == "audio/wav"
    assert artifact["sample_rate"] == 44100

    download = client.post(f"/api/v1/artifacts/{artifact['asset_id']}/download-url", headers=auth(TOKEN_A))
    assert download.status_code == 200
    url = download.json()["url"]
    content = client.get(url)
    assert content.status_code == 200
    assert content.content[:4] == b"RIFF"
    assert content.headers["accept-ranges"] == "bytes"


def test_download_token_required_and_range(client, orch) -> None:
    job_id = _run_pipeline(client, orch)
    asset_id = client.get(f"/api/v1/jobs/{job_id}/artifacts", headers=auth(TOKEN_A)).json()["artifacts"][0]["asset_id"]
    bad = client.get(f"/api/v1/artifacts/{asset_id}/content?token=nope")
    assert bad.status_code == 403

    url = client.post(f"/api/v1/artifacts/{asset_id}/download-url", headers=auth(TOKEN_A)).json()["url"]
    ranged = client.get(url, headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206
    assert len(ranged.content) == 100
    assert ranged.headers["content-range"].startswith("bytes 0-99/")


def test_cross_owner_asset_paths(client, orch) -> None:
    job_id = _run_pipeline(client, orch)
    asset_id = client.get(f"/api/v1/jobs/{job_id}/artifacts", headers=auth(TOKEN_A)).json()["artifacts"][0]["asset_id"]
    other = client.post(f"/api/v1/artifacts/{asset_id}/download-url", headers=auth("Bearer user-b-secret-token"))
    assert other.status_code == 404


def test_fixture_is_deterministic(client, orch) -> None:
    first = _run_pipeline(client, orch, key="det-1")
    second = _run_pipeline(client, orch, key="det-2")
    with orch.db.session() as session:
        hashes = [
            asset.sha256
            for asset in session.execute(select(Asset).where(Asset.job_id.in_([first, second]))).scalars()
        ]
    assert len(hashes) == 2
    assert hashes[0] == hashes[1]


def test_duplicate_delivery_does_not_run_twice(client, orch) -> None:
    job_id = _job_id(client)
    orch.queue.publish("oal:queue:ace-step-1.5", job_id)
    orch.queue.publish("oal:queue:ace-step-1.5", job_id)
    orch.worker.run_once()
    orch.worker.run_once()
    assert _status(orch.db, job_id) == "succeeded"
    with orch.db.session() as session:
        attempts = list(session.execute(select(JobAttempt).where(JobAttempt.job_id == job_id)).scalars())
    assert len(attempts) == 1


def test_stale_lease_callback_fails(client, orch) -> None:
    job_id = _job_id(client)
    orch.dispatcher.publish_once()
    claim = claim_attempt(orch.db, job_id, "test-fixture")
    assert claim is not None
    _, attempt_id, _ = claim
    outcome = complete_attempt(
        orch.db, orch.storage, orch.settings, job_id, attempt_id, "wrong-token", ("mix_wav", b"RIFFjunk")
    )
    assert outcome == "stale"


def test_cancel_beats_late_completion(client, orch) -> None:
    job_id = _job_id(client)
    orch.dispatcher.publish_once()
    claim_attempt(orch.db, job_id, "test-fixture")
    cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel", headers=auth(TOKEN_A))
    assert cancelled.json()["status"] == "cancelling"

    with orch.db.session() as session:
        attempt = session.execute(select(JobAttempt).where(JobAttempt.job_id == job_id)).scalar_one()
        token = attempt.lease_token
    outcome = complete_attempt(orch.db, orch.storage, orch.settings, job_id, attempt.id, token, ("mix_wav", b"RIFFjunk"))
    assert outcome == "discarded"
    assert _status(orch.db, job_id) == "cancelled"
    artifacts = client.get(f"/api/v1/jobs/{job_id}/artifacts", headers=auth(TOKEN_A)).json()["artifacts"]
    assert artifacts == []


def test_interrupted_recovery_requeues(client, orch) -> None:
    job_id = _job_id(client)
    orch.dispatcher.publish_once()
    claim_attempt(orch.db, job_id, "test-fixture")
    with orch.db.session() as session:
        attempt = session.execute(select(JobAttempt).where(JobAttempt.job_id == job_id)).scalar_one()
        attempt.heartbeat_at = utcnow() - timedelta(seconds=orch.settings.lease_seconds + 5)
        session.commit()

    assert orch.dispatcher.reconcile_once() == 1
    assert _status(orch.db, job_id) == "queued"
    with orch.db.session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
        assert job.attempt_number == 2
    orch.dispatcher.publish_once()
    orch.worker.run_once()
    assert _status(orch.db, job_id) == "succeeded"


def test_attempt_budget_exhausted(client, orch) -> None:
    from app.orchestration import Dispatcher

    job_id = _job_id(client)
    orch.dispatcher.publish_once()
    claim_attempt(orch.db, job_id, "test-fixture")
    with orch.db.session() as session:
        attempt = session.execute(select(JobAttempt).where(JobAttempt.job_id == job_id)).scalar_one()
        attempt.heartbeat_at = utcnow() - timedelta(seconds=orch.settings.lease_seconds + 5)
        session.commit()

    strict = Dispatcher(orch.db, orch.queue, orch.settings.model_copy(update={"max_attempts": 1}))
    strict.reconcile_once()
    assert _status(orch.db, job_id) == "failed"
    with orch.db.session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
    assert job.error_code == "MAX_ATTEMPTS"


def test_corrupt_artifact_fails(client, orch, monkeypatch) -> None:
    monkeypatch.setattr("app.worker.generate_fixture_wav", lambda *args, **kwargs: b"not-a-wav")
    job_id = _run_pipeline(client, orch)
    assert _status(orch.db, job_id) == "failed"
    with orch.db.session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one()
    assert job.error_code == "ARTIFACT_INVALID"


def test_expiry_invalidates_download_and_deletes_object(client, orch) -> None:
    job_id = _run_pipeline(client, orch)
    with orch.db.session() as session:
        asset = session.execute(select(Asset).where(Asset.job_id == job_id)).scalar_one()
        asset_key = asset.storage_key
        asset_id = asset.id
        asset.expires_at = utcnow() - timedelta(seconds=1)
        session.commit()

    assert expire_once(orch.db, orch.storage) == 1
    assert not orch.storage.exists(asset_key)

    artifact = client.get(f"/api/v1/jobs/{job_id}/artifacts", headers=auth(TOKEN_A)).json()["artifacts"]
    assert artifact == []
    download = client.post(f"/api/v1/artifacts/{asset_id}/download-url", headers=auth(TOKEN_A))
    assert download.status_code == 410


def test_sse_replay_with_last_event_id(client, orch) -> None:
    job_id = _run_pipeline(client, orch)
    with orch.db.session() as session:
        events = list(
            session.execute(select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.id)).scalars()
        )
    names = [event.event for event in events]
    assert names[0] == "queued"
    assert "succeeded" in names

    first_id = events[0].id
    replay = client.get(
        f"/api/v1/jobs/{job_id}/events",
        headers=auth(TOKEN_A, **{"Last-Event-ID": f"{job_id}-{first_id}"}),
    )
    body = replay.text
    assert "event: queued" not in body
    assert "event: succeeded" in body
