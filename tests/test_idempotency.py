from __future__ import annotations

import threading

from conftest import auth, submit, submit_body


def test_same_key_same_payload_returns_original_job(client) -> None:
    first = submit(client, key="dup", **{})
    second = submit(client, key="dup", **{})
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]


def test_same_key_different_payload_conflicts(client) -> None:
    first = submit(client, key="dup")
    changed = client.post(
        "/api/v1/jobs",
        json=submit_body(music_description="Different direction."),
        headers=auth(**{"Idempotency-Key": "dup"}),
    )
    assert first.status_code == 202
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert changed.json()["error"]["details"]["job_id"] == first.json()["job_id"]


def test_different_keys_create_different_jobs(client) -> None:
    first = submit(client, key="k1")
    second = submit(client, key="k2")
    assert first.json()["job_id"] != second.json()["job_id"]


def test_idempotency_scoped_per_owner(client) -> None:
    first = submit(client, token="Bearer user-a-secret-token", key="shared")
    second = submit(client, token="Bearer user-b-secret-token", key="shared")
    assert first.json()["job_id"] != second.json()["job_id"]


def test_concurrent_duplicate_submit_creates_one_job(client) -> None:
    results: list[tuple[int, str]] = []
    barrier = threading.Barrier(2)

    def send() -> None:
        barrier.wait()
        response = client.post(
            "/api/v1/jobs",
            json=submit_body(),
            headers=auth(**{"Idempotency-Key": "race"}),
        )
        results.append((response.status_code, response.json().get("job_id", "")))

    threads = [threading.Thread(target=send) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert [code for code, _ in results] == [202, 202]
    assert results[0][1] == results[1][1]

    from app.db import Db
    from app.models import Job
    from sqlalchemy import func, select

    db = Db(client.app.state.settings.database_url)
    with db.session() as session:
        count = session.execute(select(func.count()).select_from(Job)).scalar_one()
    assert count == 1
