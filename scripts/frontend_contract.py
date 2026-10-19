#!/usr/bin/env python3
"""External frontend contract demonstration (stdlib only, no framework).

Runs the full documented journey against a live origin: discovery, final
lyrics submission, polling, artifacts, signed download with Range, project +
immutable version, export job (MP3 + separated stems + ZIP) and delivery.

Usage: OAL_BASE_URL=http://127.0.0.1:50555 python scripts/frontend_contract.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
import zipfile

BASE = os.environ.get("OAL_BASE_URL", "http://127.0.0.1:50555").rstrip("/")
API = f"{BASE}/api/v1"
TOKEN = os.environ.get("OAL_CONTRACT_TOKEN", "contract-demo-token")
LYRICS = "[Verse]\nDawn on the county road again\n[Chorus]\nHold on, hold on\n"


def request(method: str, path: str, body: dict | bytes | None = None, headers: dict[str, str] | None = None, raw: bool = False):
    url = path if path.startswith("http") else (f"{BASE}{path}" if path.startswith("/api") else f"{API}{path}")
    data = None
    hdrs = {"Authorization": f"Bearer {TOKEN}", **(headers or {})}
    if isinstance(body, (bytes, bytearray)):
        data = body
    elif body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = resp.read()
            return resp.status, (payload if raw else json.loads(payload or b"{}")), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        if raw:
            return exc.code, payload, dict(exc.headers)
        try:
            return exc.code, json.loads(payload or b"{}"), dict(exc.headers)
        except json.JSONDecodeError:
            return exc.code, {"raw": payload[:200].decode("utf-8", "replace")}, dict(exc.headers)


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}  {detail}")
    if not condition:
        sys.exit(1)


def wait_for_job(job_id: str, timeout: float, label: str) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, detail, _ = request("GET", f"/jobs/{job_id}")
        if detail["status"] in ("succeeded", "failed", "cancelled"):
            check(f"{label} terminal", detail["status"] == "succeeded", detail.get("error_code") or "")
            return detail
        time.sleep(2)
    raise SystemExit(f"{label} timed out")


def main() -> None:
    print(f"OpenAudioLab frontend contract demo against {BASE}")

    status, health, _ = request("GET", "/health/live")
    check("health", status == 200 and health["status"] == "live")

    status, models, _ = request("GET", "/models")
    check("model discovery", status == 200 and any(m["model_id"] == "ace-step-1.5" for m in models))

    job_body = {
        "operation": "music.generate",
        "model_id": "ace-step-1.5",
        "music_description": "Jangly country rock, male vocal, warm and bright.",
        "lyrics": LYRICS,
        "lyrics_origin": "frontend_llm",
        "duration_seconds": 12,
        "seed": 42,
        "outputs": ["mix_wav"],
    }
    status, accepted, _ = request("POST", "/jobs", job_body, {"Idempotency-Key": f"contract-{uuid.uuid4()}"})
    check("submit vocal job", status == 202, accepted.get("job_id", ""))
    job_id = accepted["job_id"]
    wait_for_job(job_id, 300, "generation")

    status, artifacts, _ = request("GET", f"/jobs/{job_id}/artifacts")
    mix = next(a for a in artifacts["artifacts"] if a["role"] == "mix_wav")
    check("real artifact", mix["synthetic_test_audio"] is False and mix["sample_rate"] == 48000)

    status, signed, _ = request("POST", f"/artifacts/{mix['asset_id']}/download-url")
    check("signed download url", status == 200 and "token=" in signed["url"])
    full = request("GET", signed["url"], raw=True)[1]
    ranged_status, ranged, headers = request("GET", signed["url"], headers={"Range": "bytes=0-99"}, raw=True)
    check("playback delivery", len(full) > 1000 and ranged_status == 206 and len(ranged) == 100,
          f"{len(full)} bytes, 48kHz stereo WAV via Range 206")

    status, project, _ = request("POST", "/projects", {"name": "Contract demo"})
    check("project created", status == 201)
    project_id = project["project_id"]

    status, version, _ = request("POST", f"/projects/{project_id}/versions", {"source_job_id": job_id, "label": "demo take"})
    check("immutable version", status == 201 and version["manifest"]["lyrics_sha256"] is not None)
    version_id = version["version_id"]

    status, stale, _ = request("PATCH", f"/projects/{project_id}", {"name": "Renamed"}, {"If-Match": '"999"'})
    check("optimistic concurrency", status == 412)
    current = request("GET", f"/projects/{project_id}")[1]
    status, patched, _ = request("PATCH", f"/projects/{project_id}", {"name": "Renamed"}, {"If-Match": current["etag"]})
    check("etag edit", status == 200 and patched["etag"] != current["etag"])

    export_body = {
        "source_version_id": version_id,
        "outputs": ["mix_mp3", "stems_wav", "stems_zip"],
        "mp3": {"bitrate_kbps": 320},
    }
    status, export, _ = request("POST", "/exports", export_body, {"Idempotency-Key": f"contract-{uuid.uuid4()}"})
    check("export queued", status == 202, export.get("job_id", ""))
    wait_for_job(export["job_id"], 900, "export")

    status, export_artifacts, _ = request("GET", f"/jobs/{export['job_id']}/artifacts")
    by_role = {a["role"]: a for a in export_artifacts["artifacts"]}
    check("mp3 export", "mix_mp3" in by_role and by_role["mix_mp3"]["mime"] == "audio/mpeg")
    stems = [a for a in export_artifacts["artifacts"] if a["stem_source"] == "separated"]
    check("separated stems", len(stems) == 4, ",".join(sorted(a["stem_category"] for a in stems)))

    zip_url = request("POST", f"/artifacts/{by_role['stems_zip']['asset_id']}/download-url")[1]["url"]
    zip_body = request("GET", zip_url, raw=True)[1]
    with zipfile.ZipFile(io.BytesIO(zip_body)) as archive:
        names = set(archive.namelist())
    check("stem zip contents", names == {"stems/drums.wav", "stems/bass.wav", "stems/other.wav", "stems/vocals.wav", "manifest.json"})

    mp3_url = request("POST", f"/artifacts/{by_role['mix_mp3']['asset_id']}/download-url")[1]["url"]
    mp3_body = request("GET", mp3_url, raw=True)[1]
    check("mp3 delivered", len(mp3_body) > 1000, f"{len(mp3_body)} bytes")

    print("CONTRACT OK")


if __name__ == "__main__":
    main()
