"""M21: friendly slugs, id-or-slug track resolution, download filenames."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Asset
from conftest import TOKEN_A, auth, submit_body


def _complete(client, orch, title: str, key: str):
    body = submit_body(title=title)
    r = client.post("/api/v1/jobs", json=body, headers=auth(TOKEN_A, **{"Idempotency-Key": key}))
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    orch.dispatcher.publish_once()
    orch.worker.run_once()
    with orch.db.session() as session:
        mix = session.execute(
            select(Asset).where(Asset.job_id == job_id, Asset.role == "mix_wav")
        ).scalar_one()
    return job_id, mix


def test_generated_mix_gets_title_slug(client, orch) -> None:
    _, mix = _complete(client, orch, "Sunny Midnight Drive", "s1")
    assert mix.slug == "sunny-midnight-drive"


def test_slug_unique_for_repeated_title(client, orch) -> None:
    _, a = _complete(client, orch, "Same Name", "s2")
    _, b = _complete(client, orch, "Same Name", "s3")
    assert a.slug and b.slug and a.slug != b.slug
    assert a.slug == "same-name"
    assert b.slug.startswith("same-name-")


def test_public_track_resolves_by_id_or_slug(client, orch) -> None:
    _, mix = _complete(client, orch, "Public Song", "s4")
    assert client.patch(f"/api/v1/artifacts/{mix.id}", json={"shared": True}, headers=auth(TOKEN_A)).status_code == 200
    by_slug = client.get(f"/api/v1/public/tracks/{mix.slug}")
    assert by_slug.status_code == 200
    assert by_slug.json()["asset_id"] == mix.id
    assert by_slug.json()["slug"] == mix.slug
    assert client.get(f"/api/v1/public/tracks/{mix.id}").status_code == 200


def test_tracks_listing_exposes_slug(client, orch) -> None:
    _, mix = _complete(client, orch, "Listed Tune", "s5")
    tracks = client.get("/api/v1/tracks", headers=auth(TOKEN_A)).json()["tracks"]
    row = next(t for t in tracks if t["asset_id"] == mix.id)
    assert row["slug"] == "listed-tune"


def test_content_download_sets_friendly_disposition(client, orch) -> None:
    _, mix = _complete(client, orch, "Dispo Track", "s6")
    url = client.post(f"/api/v1/artifacts/{mix.id}/download-url", headers=auth(TOKEN_A)).json()["url"]
    inline = client.get(url)
    assert "content-disposition" not in inline.headers
    r = client.get(f"{url}&download=1")
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert "attachment" in cd and "dispo-track" in cd and ".wav" in cd
