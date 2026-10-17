from __future__ import annotations


def test_list_models_requires_no_auth(client) -> None:
    response = client.get("/api/v1/models")
    assert response.status_code == 200
    models = {item["model_id"]: item for item in response.json()}
    assert models["ace-step-1.5"]["availability"] == "available"
    assert models["heartmula"]["availability"] == "disabled"
    assert models["minimax-music-3"]["commercial_policy"] == "conditional"


def test_model_detail_has_revision_and_controls(client) -> None:
    response = client.get("/api/v1/models/ace-step-1.5")
    assert response.status_code == 200
    body = response.json()
    assert body["revision"]
    assert "mood" in body["supported_controls"] and "variations" in body["supported_controls"]
    assert set(body["output_options"]) == {"mix_wav", "mix_mp3", "stems_wav", "stems_zip"}


def test_unknown_model_404_envelope(client) -> None:
    response = client.get("/api/v1/models/nope")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MODEL_NOT_FOUND"
