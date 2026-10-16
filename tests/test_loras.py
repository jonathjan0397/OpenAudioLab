from __future__ import annotations

from conftest import submit

from app.models import Lora

CREDS_LAB = ("admin", "3671A113a05786!")


def _seed_lora(orch, **overrides) -> str:
    from app.models import new_uuid, utcnow

    fields = dict(
        id=new_uuid(),
        name=f"lora-{new_uuid()[:8]}",
        kind="style",
        tags_json=["pop"],
        storage_prefix="loras/seed",
        files_json=["adapter_model.safetensors"],
        base_model_id="ace-step-1.5",
        base_revision="1.5.0@ca1e85f",
        default_scale=1.0,
        state="active",
        provenance="external",
        created_at=utcnow(),
    )
    fields.update(overrides)
    with orch.db.session() as session:
        row = Lora(**fields)
        session.add(row)
        session.commit()
        return row.id


def test_lora_admission(client, orch) -> None:
    lora_id = _seed_lora(orch)
    ok = submit(client, key="gen-lora", lora_id=lora_id)
    assert ok.status_code == 202
    unknown = submit(client, key="gen-lora-unknown", lora_id="missing")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "LORA_NOT_FOUND"


def test_lora_retired_not_usable(client, orch) -> None:
    lora_id = _seed_lora(orch, state="retired")
    response = submit(client, key="gen-lora-retired", lora_id=lora_id)
    assert response.status_code == 404


def test_lora_incompatible_base(client, orch) -> None:
    lora_id = _seed_lora(orch, base_model_id="heartmula")
    response = submit(client, key="gen-lora-bad", lora_id=lora_id)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LORA_INCOMPATIBLE"


def test_lora_profile_conflict(client, orch) -> None:
    lora_id = _seed_lora(orch)
    response = submit(
        client, key="gen-both", lora_id=lora_id, artist_profile_version_id="whatever"
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "LORA_PROFILE_CONFLICT"


def test_lab_loras_endpoint(client, orch) -> None:
    lora_id = _seed_lora(orch, name="seed-pop", kind="genre", tags_json=["pop", "dance"])
    _seed_lora(orch, name="retired-one", state="retired")
    response = client.get("/lab/api/loras", auth=CREDS_LAB)
    assert response.status_code == 200
    items = response.json()["loras"]
    by_id = {item["id"]: item for item in items}
    assert lora_id in by_id
    assert by_id[lora_id]["name"] == "seed-pop"
    assert by_id[lora_id]["kind"] == "genre"
    assert by_id[lora_id]["tags"] == ["pop", "dance"]
    assert all(item["name"] != "retired-one" for item in items)


def test_lab_upload_and_tags(client, orch) -> None:
    response = client.post(
        "/lab/api/upload",
        auth=CREDS_LAB,
        files={"file": ("tone.wav", b"RIFFfake-wav-bytes", "audio/wav")},
    )
    assert response.status_code == 201
    asset_id = response.json()["asset_id"]
    assert response.json()["tags"] == []
    listing = client.get("/lab/api/artifacts", auth=CREDS_LAB).json()["artifacts"]
    uploaded = [a for a in listing if a["asset_id"] == asset_id]
    assert uploaded and uploaded[0]["kind"] == "uploaded"
    tagged = client.post(
        f"/lab/api/assets/{asset_id}/tags",
        auth=CREDS_LAB,
        json={"tags": ["genre:pop", "mood:warm"]},
    )
    assert tagged.status_code == 200
    listing = client.get("/lab/api/artifacts", auth=CREDS_LAB).json()["artifacts"]
    uploaded = [a for a in listing if a["asset_id"] == asset_id][0]
    assert uploaded["tags"] == ["genre:pop", "mood:warm"]
