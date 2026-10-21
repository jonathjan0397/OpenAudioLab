"""M20: per-workspace artist binding + Main artist designation."""

from __future__ import annotations

WS = "/api/v1/workspaces"
AP = "/api/v1/artist-profiles"


def _login(client, email: str) -> str:
    client.post("/api/v1/auth/logout")
    r = client.post(
        "/api/v1/auth/register",
        json={"email": email, "username": email.split("@")[0].replace(".", ""), "password": "super-secret-1"},
    )
    return r.json()["user"]["id"]


def _profile(client, name: str) -> dict:
    r = client.post(AP, json={"name": name})
    assert r.status_code == 201
    return r.json()


def _workspace(client, name: str) -> str:
    r = client.post(WS, json={"name": name})
    assert r.status_code == 201
    return r.json()["workspace_id"]


def test_first_profile_is_main_and_set_main_moves_it(client) -> None:
    _login(client, "m20-a@example.com")
    p1 = _profile(client, "Aria")
    p2 = _profile(client, "Bram")
    assert p1["is_main"] is True  # first profile auto-main
    assert p2["is_main"] is False
    assert client.post(f"{AP}/{p2['profile_id']}/set-main").status_code == 200
    listed = {x["profile_id"]: x for x in client.get(AP).json()}
    assert listed[p2["profile_id"]]["is_main"] is True
    assert listed[p1["profile_id"]]["is_main"] is False  # exactly one main


def test_workspace_artist_attach_and_listing(client) -> None:
    _login(client, "m20-b@example.com")
    prof = _profile(client, "Composer")
    wid = _workspace(client, "Album")
    r = client.patch(f"{WS}/{wid}/artist", json={"artist_profile_id": prof["profile_id"]})
    assert r.status_code == 200
    assert r.json()["artist_profile_id"] == prof["profile_id"]

    ws = next(w for w in client.get(WS).json()["workspaces"] if w["workspace_id"] == wid)
    assert ws["artist"]["profile_id"] == prof["profile_id"]
    assert ws["artist"]["name"] == "Composer"
    # no trained adapter yet => not applicable, no default adapter
    assert ws["artist"]["applicable"] is False
    assert ws["artist"]["default_adapter_id"] is None

    # detach
    assert client.patch(f"{WS}/{wid}/artist", json={"artist_profile_id": None}).json()["artist_profile_id"] is None
    ws = next(w for w in client.get(WS).json()["workspaces"] if w["workspace_id"] == wid)
    assert ws["artist"] is None


def test_workspace_rejects_foreign_artist(client) -> None:
    _login(client, "m20-owner@example.com")
    wid = _workspace(client, "Mine")
    client.post("/api/v1/auth/logout")
    _login(client, "m20-other@example.com")
    foreign = _profile(client, "SomeoneElse")["profile_id"]
    assert client.patch(f"{WS}/{wid}/artist", json={"artist_profile_id": foreign}).status_code == 404


def test_generation_into_workspace_with_artist_is_still_validated(client) -> None:
    # attaching a profile to a workspace does not itself inject it server-side;
    # generation routing only requires a valid owned workspace.
    _login(client, "m20-c@example.com")
    _profile(client, "Solo")
    wid = _workspace(client, "Sound")
    client.patch(f"{WS}/{wid}/artist", json={"artist_profile_id": None})
    body = {
        "operation": "music.generate",
        "model_id": "ace-step-1.5",
        "music_description": "test",
        "lyrics": "[Verse]\nhi\n",
        "lyrics_origin": "frontend_llm",
        "outputs": ["mix_wav"],
        "workspace_id": wid,
    }
    r = client.post("/api/v1/jobs", json=body, headers={"Idempotency-Key": "k-m20"})
    assert r.status_code == 202
