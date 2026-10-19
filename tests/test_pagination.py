from __future__ import annotations

from conftest import auth


def _create(client, count: int) -> None:
    for index in range(count):
        response = client.post(
            "/api/v1/jobs",
            json={
                "operation": "music.generate",
                "model_id": "ace-step-1.5",
                "music_description": f"Direction {index}.",
                "lyrics": "line\n",
            },
            headers=auth(**{"Idempotency-Key": f"page-{index}"}),
        )
        assert response.status_code == 202


def test_cursor_pagination_newest_first(client) -> None:
    _create(client, 3)
    page1 = client.get("/api/v1/jobs?limit=2", headers=auth()).json()
    assert len(page1["jobs"]) == 2
    assert page1["next_cursor"] is not None

    page2 = client.get(f"/api/v1/jobs?limit=2&cursor={page1['next_cursor']}", headers=auth()).json()
    assert len(page2["jobs"]) == 1
    assert page2["next_cursor"] is None

    ids = [job["job_id"] for job in page1["jobs"] + page2["jobs"]]
    assert len(set(ids)) == 3


def test_invalid_cursor_returns_422(client) -> None:
    response = client.get("/api/v1/jobs?cursor=%21%21bogus", headers=auth())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "CURSOR_INVALID"
