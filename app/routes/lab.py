"""/lab stopgap test harness: submit generations and hear the outputs.

A single self-contained page (vanilla JS) served by the control-plane backend and
guarded by HTTP Basic. It reuses the durable job-admission path (``create_job``) and
the tokenized artifact content endpoint, so it adds no new storage or queue plumbing.
This is a developer/QA surface, not part of the versioned public API.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..errors import ApiError
from ..models import ArtistProfile, ArtistProfileVersion, Asset, Job, Lora, new_uuid, utcnow
from ..orchestration import as_utc
from ..schemas import GenerateJobRequest
from .. import tagging
from ..tokens import make_token
from .jobs import create_job

router = APIRouter(tags=["lab"])
_basic = HTTPBasic()

# Content URLs are minted with a generous TTL so a browsing/listening session does
# not expire mid-playback (the public API default is a short-lived download link).
_LAB_URL_TTL_SECONDS = 3600


class LabGenerate(BaseModel):
    music_description: str = Field(min_length=1, max_length=2000)
    duration_seconds: int | None = Field(default=30, ge=1, le=600)
    instrumental: bool = True
    model_id: str = "ace-step-1.5"
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    artist_profile_version_id: str | None = None
    lora_id: str | None = None


class _RequestShim:
    """Minimal stand-in exposing what ``create_job`` reads from a Request."""

    def __init__(self, app: Any, headers: dict[str, str]) -> None:
        self.app = app
        self.headers = headers


def _lab_owner(token: str) -> str:
    return "tok_" + hashlib.sha256(token.encode("utf-8")).hexdigest()[:32]


def require_lab(
    request: Request, credentials: HTTPBasicCredentials = Depends(_basic)
) -> HTTPBasicCredentials:
    settings = request.app.state.settings
    user_ok = secrets.compare_digest(credentials.username or "", settings.lab_basic_user)
    pass_ok = secrets.compare_digest(credentials.password or "", settings.lab_basic_password)
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=401,
            detail="Invalid lab credentials.",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials


def _content_url(settings: Any, asset_id: str) -> str:
    expiry = utcnow() + timedelta(seconds=_LAB_URL_TTL_SECONDS)
    return f"/api/v1/artifacts/{asset_id}/content?token={make_token(settings.secret_key, asset_id, expiry)}"


@router.get("/lab", response_class=HTMLResponse)
def lab_page(request: Request, _: HTTPBasicCredentials = Depends(require_lab)) -> HTMLResponse:
    return HTMLResponse(_PAGE_HTML, headers={"Cache-Control": "no-store"})


@router.get("/lab/api/artifacts")
def lab_artifacts(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    _: HTTPBasicCredentials = Depends(require_lab),
) -> JSONResponse:
    settings = request.app.state.settings
    now = utcnow()
    with request.app.state.db.session() as session:
        rows = list(
            session.execute(
                select(Asset)
                .where(Asset.deleted_at.is_(None), Asset.mime.like("audio/%"))
                .order_by(Asset.created_at.desc(), Asset.id.desc())
                .limit(limit)
            ).scalars()
        )
    items = []
    for asset in rows:
        expired = asset.expires_at is not None and as_utc(asset.expires_at) <= now
        items.append(
            {
                "asset_id": asset.id,
                "job_id": asset.job_id,
                "role": asset.role,
                "mime": asset.mime,
                "duration_seconds": asset.duration_seconds,
                "bytes": asset.bytes,
                "sample_rate": asset.sample_rate,
                "channels": asset.channels,
                "synthetic": asset.synthetic,
                "kind": asset.kind,
                "tags": list(asset.tags_json or []),
                "expired": expired,
                "created_at": asset.created_at.isoformat() if asset.created_at else None,
                "url": _content_url(settings, asset.id),
            }
        )
    return JSONResponse({"artifacts": items})


@router.post("/lab/api/generate")
def lab_generate(
    payload: LabGenerate,
    request: Request,
    _: HTTPBasicCredentials = Depends(require_lab),
) -> JSONResponse:
    settings = request.app.state.settings
    body: dict[str, Any] = {
        "operation": "music.generate",
        "model_id": payload.model_id,
        "music_description": payload.music_description,
        "instrumental": payload.instrumental,
        "outputs": ["mix_wav"],
    }
    if payload.duration_seconds is not None:
        body["duration_seconds"] = payload.duration_seconds
    if payload.seed is not None:
        body["seed"] = payload.seed
    owner = _lab_owner(settings.lab_owner_token)
    if payload.lora_id:
        body["lora_id"] = payload.lora_id
    if payload.artist_profile_version_id:
        body["artist_profile_version_id"] = payload.artist_profile_version_id
        with request.app.state.db.session() as session:
            version = session.get(ArtistProfileVersion, payload.artist_profile_version_id)
        if version is None:
            raise ApiError(404, "PROFILE_VERSION_NOT_FOUND", "Artist profile version not found.")
        owner = version.owner_id
    gen = GenerateJobRequest(**body)
    shim = _RequestShim(request.app, {"Idempotency-Key": f"lab-{uuid4().hex}"})
    return create_job(gen, shim, owner)


@router.post("/lab/api/llm")
def lab_llm(
    payload: dict[str, Any],
    request: Request,
    _: HTTPBasicCredentials = Depends(require_lab),
) -> JSONResponse:
    from ..llm import LYRICS_SYSTEM, STYLE_SYSTEM

    client = getattr(request.app.state, "llm", None)
    if client is None:
        raise ApiError(503, "LLM_DISABLED", "The lyrics assistant is not configured.")
    task = payload.get("task", "lyrics")
    text_in = str(payload.get("input", ""))[:2000]
    if task == "style":
        system, user, max_tokens = STYLE_SYSTEM, text_in, 60
    else:
        system, user, max_tokens = LYRICS_SYSTEM, f"Write song lyrics for: {text_in}", 420
    try:
        text = client.chat(system, user, max_tokens=max_tokens)
    except Exception as exc:
        raise ApiError(502, "LLM_UNAVAILABLE", str(exc)[:200])
    return JSONResponse({"text": text})


@router.get("/lab/api/profiles")
def lab_profiles(
    request: Request,
    _: HTTPBasicCredentials = Depends(require_lab),
) -> JSONResponse:
    with request.app.state.db.session() as session:
        rows = list(
            session.execute(
                select(ArtistProfileVersion, ArtistProfile.name)
                .join(ArtistProfile, ArtistProfile.id == ArtistProfileVersion.profile_id)
                .where(ArtistProfile.deleted_at.is_(None))
                .order_by(ArtistProfileVersion.created_at.desc())
                .limit(50)
            )
            .tuples()
        )
    items = [
        {
            "version_id": version.id,
            "profile_id": version.profile_id,
            "profile_name": name,
            "mechanism": version.mechanism,
            "base_model_id": version.base_model_id,
            "state": version.state,
            "evaluation_status": version.evaluation_status,
            "created_at": version.created_at.isoformat() if version.created_at else None,
        }
        for version, name in rows
    ]
    return JSONResponse({"profiles": items})


@router.get("/lab/api/loras")
def lab_loras(
    request: Request,
    _: HTTPBasicCredentials = Depends(require_lab),
) -> JSONResponse:
    with request.app.state.db.session() as session:
        rows = list(
            session.execute(
                select(Lora).where(Lora.state == "active").order_by(Lora.kind, Lora.name)
            )
            .scalars()
        )
    items = [
        {
            "id": lora.id,
            "name": lora.name,
            "kind": lora.kind,
            "tags": list(lora.tags_json or []),
            "base_model_id": lora.base_model_id,
            "default_scale": lora.default_scale,
            "provenance": lora.provenance,
        }
        for lora in rows
    ]
    return JSONResponse({"loras": items})


class LabTags(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=40)


@router.post("/lab/api/upload")
async def lab_upload(
    request: Request,
    file: UploadFile = File(...),
    _: HTTPBasicCredentials = Depends(require_lab),
) -> JSONResponse:
    settings = request.app.state.settings
    body = await file.read()
    if not body:
        raise ApiError(422, "EMPTY_UPLOAD", "Uploaded file is empty.")
    asset_id = new_uuid()
    suffix = (file.filename or "upload.bin").rsplit("/", 1)[-1]
    storage_key = f"owners/{_lab_owner(settings.lab_owner_token)}/uploads/{asset_id}/{suffix}"
    request.app.state.storage.put(storage_key, body)
    fp = None
    if suffix.lower().endswith((".wav", ".mp3", ".flac", ".ogg", ".m4a")):
        import tempfile
        from pathlib import Path

        with tempfile.NamedTemporaryFile(suffix="-" + suffix.rsplit(".", 1)[-1], delete=False) as tmp:
            tmp.write(body)
            tmp_path = Path(tmp.name)
        try:
            fp = tagging.fingerprint(tmp_path)
        finally:
            tmp_path.unlink(missing_ok=True)
    matches = []
    if fp:
        matches = tagging.acoustid_lookup(fp["signature"], fp["duration"], settings.acoustid_client_key)
    tags = tagging.tags_from_matches(matches)
    with request.app.state.db.session() as session:
        session.add(
            Asset(
                id=asset_id,
                job_id="upload",
                owner_id=_lab_owner(settings.lab_owner_token),
                storage_key=storage_key,
                role="reference",
                kind="uploaded",
                mime=file.content_type or "application/octet-stream",
                bytes=len(body),
                sha256=hashlib.sha256(body).hexdigest(),
                duration_seconds=fp["duration"] if fp else None,
                synthetic=False,
                tags_json=tags,
            )
        )
        session.commit()
    return JSONResponse({"asset_id": asset_id, "tags": tags, "matches": matches}, status_code=201)


@router.post("/lab/api/assets/{asset_id}/tags")
def lab_set_tags(
    asset_id: str,
    payload: LabTags,
    request: Request,
    _: HTTPBasicCredentials = Depends(require_lab),
) -> JSONResponse:
    with request.app.state.db.session() as session:
        asset = session.execute(select(Asset).where(Asset.id == asset_id)).scalar_one_or_none()
        if asset is None:
            raise ApiError(404, "ASSET_NOT_FOUND", "Asset not found.")
        asset.tags_json = payload.tags
        session.commit()
    return JSONResponse({"asset_id": asset_id, "tags": payload.tags})


@router.get("/lab/api/jobs/{job_id}")
def lab_job(
    job_id: str,
    request: Request,
    _: HTTPBasicCredentials = Depends(require_lab),
) -> JSONResponse:
    settings = request.app.state.settings
    with request.app.state.db.session() as session:
        job = session.execute(select(Job).where(Job.id == job_id)).scalar_one_or_none()
        if job is None:
            raise ApiError(404, "JOB_NOT_FOUND", "Job not found.")
        status, stage = job.status, job.stage
        progress, error_code, error_message = job.progress, job.error_code, job.error_message
        assets = list(
            session.execute(
                select(Asset)
                .where(Asset.job_id == job.id, Asset.deleted_at.is_(None))
                .order_by(Asset.created_at)
            ).scalars()
        )
    artifacts = [
        {
            "asset_id": asset.id,
            "role": asset.role,
            "mime": asset.mime,
            "duration_seconds": asset.duration_seconds,
            "url": _content_url(settings, asset.id),
        }
        for asset in assets
        if asset.mime.startswith("audio/")
    ]
    return JSONResponse(
        {
            "job_id": job_id,
            "status": status,
            "stage": stage,
            "progress": progress,
            "error_code": error_code,
            "error_message": error_message,
            "artifacts": artifacts,
        }
    )


_PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:,">
<title>OpenAudioLab - Test Harness</title>
<style>
  :root { color-scheme: light dark; }
  body { font: 15px/1.5 system-ui, sans-serif; margin: 0; background: #0f1115; color: #e6e8ec; }
  header { padding: 16px 24px; border-bottom: 1px solid #23262e; display: flex; align-items: baseline; gap: 12px; }
  header h1 { font-size: 18px; margin: 0; }
  header .sub { color: #8b93a1; font-size: 13px; }
  main { max-width: 860px; margin: 0 auto; padding: 24px; display: grid; gap: 28px; }
  .card { background: #161922; border: 1px solid #23262e; border-radius: 12px; padding: 20px; }
  .card h2 { font-size: 15px; margin: 0 0 14px; color: #aeb6c2; text-transform: uppercase; letter-spacing: .04em; }
  label { display: block; font-size: 13px; color: #8b93a1; margin: 10px 0 4px; }
  textarea, input, select { width: 100%; box-sizing: border-box; background: #0f1115; color: #e6e8ec; border: 1px solid #2a2f3a; border-radius: 8px; padding: 8px 10px; font: inherit; }
  textarea { min-height: 68px; resize: vertical; }
  .row { display: flex; gap: 14px; flex-wrap: wrap; }
  .row > div { flex: 1 1 140px; }
  .check { display: flex; align-items: center; gap: 8px; margin-top: 22px; }
  .check input { width: auto; }
  button { background: #3b82f6; color: white; border: 0; border-radius: 8px; padding: 10px 16px; font: inherit; cursor: pointer; }
  button:disabled { opacity: .5; cursor: default; }
  button.ghost { background: #23262e; color: #cfd4dc; }
  .status { margin-top: 12px; font-size: 13px; color: #8b93a1; min-height: 18px; }
  .result { margin-top: 14px; }
  audio { width: 100%; margin-top: 8px; }
  ul.artifacts { list-style: none; margin: 0; padding: 0; display: grid; gap: 14px; }
  .art { border-bottom: 1px solid #23262e; padding-bottom: 12px; }
  .meta { font-size: 12px; color: #8b93a1; display: flex; gap: 12px; flex-wrap: wrap; }
  .tag { background: #23262e; border-radius: 6px; padding: 1px 7px; }
  .empty { color: #8b93a1; font-size: 13px; }
  a { color: #7aa7ff; }
</style>
</head>
<body>
<noscript><p style="padding:12px 24px;color:#e6b450">This page needs JavaScript enabled.</p></noscript>
<header><h1>OpenAudioLab</h1><span class="sub">test harness</span></header>
<main>
  <section class="card">
    <h2>Generate</h2>
    <label for="desc">Music description</label>
    <textarea id="desc" placeholder="e.g. warm ambient pad, slow tempo, reverb">warm ambient pad, slow tempo, soft reverb</textarea>
    <div class="row">
      <div><label for="dur">Duration (s)</label><input id="dur" type="number" min="1" max="600" value="30"></div>
      <div><label for="seed">Seed (optional)</label><input id="seed" type="number" min="0" placeholder="random"></div>
      <div class="check"><input id="inst" type="checkbox" checked><label for="inst" style="margin:0">Instrumental</label></div>
    </div>
    <label for="profile">LoRA profile</label>
    <div style="display:flex;gap:10px">
      <select id="profile"><option value="">base model (no LoRA)</option></select>
      <button class="ghost" id="profrefresh" style="flex:0 0 auto">Refresh</button>
    </div>
    <label for="lora">Registry LoRA</label>
    <div style="display:flex;gap:10px">
      <select id="lora"><option value="">none</option></select>
      <button class="ghost" id="lorarefresh" style="flex:0 0 auto">Refresh</button>
    </div>
    <div style="margin-top:16px"><button id="go">Generate</button></div>
    <div class="status" id="status"></div>
    <div class="result" id="result"></div>
  </section>

  <section class="card">
    <h2>Upload &amp; identify</h2>
    <input id="file" type="file" accept="audio/*">
    <div style="margin-top:12px"><button id="upload">Upload &amp; identify</button></div>
    <div class="status" id="ustatus"></div>
  </section>

  <section class="card">
    <h2>LLM assistant <span style="font-weight:400;font-size:12px;color:#888">(lyrics + style prompts only)</span></h2>
    <select id="llm-task"><option value="lyrics">Write lyrics</option><option value="style">Style prompt</option></select>
    <input id="llm-input" placeholder="e.g. a rainy night drive" style="width:55%">
    <button id="llm-go">Ask</button>
    <div class="status" id="llm-status"></div>
    <pre id="llm-out" style="white-space:pre-wrap;margin-top:8px"></pre>
  </section>

  <section class="card">
    <h2>Artifacts <button class="ghost" id="refresh" style="float:right;padding:4px 12px">Refresh</button></h2>
    <ul class="artifacts" id="list"><li class="empty">Loading...</li></ul>
  </section>
</main>
<script>
window.onerror = function (m) {
  var l = document.getElementById("list");
  if (l) l.innerHTML = '<li class="empty">JS error: ' + m + "</li>";
  var s = document.getElementById("status");
  if (s) s.textContent = "JS error: " + m;
  return false;
};
</script>
<script>
var $ = function (id) { return document.getElementById(id); };
var esc = function (s) { return s == null ? "" : String(s).replace(/[&<>"]/g, function (c) { return ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"})[c]; }); };
var fmtTime = function (iso) { if (!iso) return ""; var d = new Date(iso); return isNaN(d) ? "" : d.toLocaleString(); };
var fmtDur = function (s) { return s == null ? "" : (Math.round(s * 10) / 10) + "s"; };

function setStatus(t) { $("status").textContent = t || ""; }

function xhr(method, url, body, cb) {
  var x = new XMLHttpRequest();
  x.open(method, url, true);
  x.onreadystatechange = function () {
    if (x.readyState !== 4) return;
    if (x.status === 0) { setStatus("Network error - is the server up?"); cb(null); return; }
    if (x.status === 401) { setStatus("Authentication failed - reload and re-enter credentials."); cb(null); return; }
    cb(x);
  };
  if (body != null) x.setRequestHeader("Content-Type", "application/json");
  x.send(body == null ? null : body);
}

function audioBlock(a) {
  var expired = a.expired ? ' <span class="tag">expired</span>' : "";
  var synth = a.synthetic ? ' <span class="tag">synthetic</span>' : "";
  return '<div class="art"><div class="meta">'
    + '<span class="tag">' + esc(a.role || "audio") + '</span>'
    + '<span>' + fmtDur(a.duration_seconds) + '</span>'
    + '<span>' + (a.bytes ? Math.round(a.bytes / 1024) + " KB" : "") + '</span>'
    + '<span>' + esc(fmtTime(a.created_at)) + '</span>' + expired + synth
    + ' <span class="tag" style="cursor:pointer" onclick="editTags(\\'' + a.asset_id + '\\')">tags: ' + esc((a.tags || []).join(", ") || "none") + '</span>'
    + '</div><audio controls preload="none" src="' + esc(a.url) + '"></audio></div>';
}

function loadArtifacts() {
  xhr("GET", "/lab/api/artifacts?limit=50", null, function (x) {
    if (!x) return;
    var data;
    try { data = JSON.parse(x.responseText); } catch (e) { return; }
    var items = data.artifacts || [];
    $("list").innerHTML = items.length
      ? items.map(audioBlock).join("")
      : '<li class="empty">No audio artifacts yet - generate one above.</li>';
  });
}

var pollTimer = null;
function pollJob(jobId) {
  xhr("GET", "/lab/api/jobs/" + encodeURIComponent(jobId), null, function (x) {
    if (!x) return;
    var job;
    try { job = JSON.parse(x.responseText); } catch (e) { return; }
    if (job.status === "succeeded") {
      setStatus("Done.");
      $("result").innerHTML = (job.artifacts || []).map(audioBlock).join("") || '<div class="empty">No audio produced.</div>';
      $("go").disabled = false;
      loadArtifacts();
      return;
    }
    if (job.status === "failed" || job.status === "cancelled") {
      setStatus("Failed: " + (job.error_code || job.status) + (job.error_message ? " - " + job.error_message : ""));
      $("go").disabled = false;
      return;
    }
    setStatus("Working... " + job.status + (job.stage ? " / " + job.stage : "") + (job.progress != null ? " (" + Math.round(job.progress * 100) + "%)" : ""));
    pollTimer = setTimeout(function () { pollJob(jobId); }, 2000);
  });
}

function loadLoras() {
  xhr("GET", "/lab/api/loras", null, function (x) {
    if (!x) return;
    var data;
    try { data = JSON.parse(x.responseText); } catch (e) { return; }
    var items = data.loras || [];
    var sel = $("lora");
    var prev = sel.value;
    sel.innerHTML = '<option value="">none</option>';
    for (var i = 0; i < items.length; i++) {
      var l = items[i];
      var opt = document.createElement("option");
      opt.value = l.id;
      opt.textContent = "[" + l.kind + "] " + l.name + (l.tags.length ? " (" + l.tags.join(", ") + ")" : "");
      sel.appendChild(opt);
    }
    if (prev) sel.value = prev;
  });
}

function loadProfiles() {
  xhr("GET", "/lab/api/profiles", null, function (x) {
    if (!x) return;
    var data;
    try { data = JSON.parse(x.responseText); } catch (e) { return; }
    var items = data.profiles || [];
    var sel = $("profile");
    var prev = sel.value;
    sel.innerHTML = '<option value="">base model (no LoRA)</option>';
    for (var i = 0; i < items.length; i++) {
      var p = items[i];
      var opt = document.createElement("option");
      opt.value = p.version_id;
      opt.textContent = p.profile_name + " - " + p.mechanism + " [" + p.state + "/" + p.evaluation_status + "]";
      sel.appendChild(opt);
    }
    if (prev) sel.value = prev;
  });
}

function generate() {
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  if (!$("desc").value.trim()) { setStatus("Enter a description first."); return; }
  var body = {
    music_description: $("desc").value.trim(),
    duration_seconds: $("dur").value ? parseInt($("dur").value, 10) : null,
    instrumental: $("inst").checked,
    model_id: "ace-step-1.5"
  };
  if ($("seed").value !== "") body.seed = parseInt($("seed").value, 10);
  if ($("profile").value) body.artist_profile_version_id = $("profile").value;
  if ($("lora").value) body.lora_id = $("lora").value;
  $("go").disabled = true; $("result").innerHTML = ""; setStatus("Submitting...");
  xhr("POST", "/lab/api/generate", JSON.stringify(body), function (x) {
    if (!x) { $("go").disabled = false; return; }
    if (x.status < 200 || x.status >= 300) {
      var err = {};
      try { err = JSON.parse(x.responseText).error || {}; } catch (e) {}
      setStatus("Rejected: " + (err.code || x.status));
      $("go").disabled = false;
      return;
    }
    var data;
    try { data = JSON.parse(x.responseText); } catch (e) { $("go").disabled = false; return; }
    setStatus("Queued " + (data.job_id || "").slice(0, 8) + "...");
    pollJob(data.job_id);
  });
}

function editTags(id) {
  var v = prompt("Tags (comma separated):");
  if (v === null) return;
  var parts = v.split(",");
  var tags = [];
  for (var i = 0; i < parts.length; i++) { var t = parts[i].trim(); if (t) tags.push(t); }
  xhr("POST", "/lab/api/assets/" + encodeURIComponent(id) + "/tags", JSON.stringify({ tags: tags }), function (x) { loadArtifacts(); });
}

function uploadFile() {
  var input = $("file");
  if (!input.files || !input.files.length) { $("ustatus").textContent = "Choose a file first."; return; }
  var fd = new FormData();
  fd.append("file", input.files[0]);
  $("upload").disabled = true;
  $("ustatus").textContent = "Uploading + fingerprinting...";
  var x = new XMLHttpRequest();
  x.open("POST", "/lab/api/upload", true);
  x.onreadystatechange = function () {
    if (x.readyState !== 4) return;
    $("upload").disabled = false;
    var data = null;
    try { data = JSON.parse(x.responseText); } catch (e) {}
    if (x.status !== 201 || !data) { $("ustatus").textContent = "Upload failed: " + x.status; return; }
    var m = (data.matches || [])[0];
    $("ustatus").textContent = "Identified: " + (m ? m.artist + " - " + m.title + " (" + Math.round(m.score * 100) + "%)" : "no match in AcoustID") + " | tags: " + (data.tags.join(", ") || "none");
    loadArtifacts();
  };
  x.send(fd);
}

function askLlm() {
  var task = $("llm-task").value;
  var input = $("llm-input").value.trim();
  if (!input) { $("llm-status").textContent = "Type something first."; return; }
  $("llm-go").disabled = true;
  $("llm-status").textContent = "Thinking...";
  $("llm-out").textContent = "";
  xhr("POST", "/lab/api/llm", JSON.stringify({ task: task, input: input }), function (x) {
    $("llm-go").disabled = false;
    if (!x) { $("llm-status").textContent = ""; return; }
    var data = null;
    try { data = JSON.parse(x.responseText); } catch (e) {}
    if (!x.status || x.status >= 400) { $("llm-status").textContent = "Error: " + ((data && data.error && data.error.code) || x.status); return; }
    $("llm-status").textContent = "";
    $("llm-out").textContent = data.text || "(empty)";
  });
}

$("go").addEventListener("click", generate);
$("refresh").addEventListener("click", loadArtifacts);
$("profrefresh").addEventListener("click", loadProfiles);
$("lorarefresh").addEventListener("click", loadLoras);
$("upload").addEventListener("click", uploadFile);
$("llm-go").addEventListener("click", askLlm);
$("lora").addEventListener("change", function () { if (this.value) $("profile").value = ""; });
$("profile").addEventListener("change", function () { if (this.value) $("lora").value = ""; });
loadArtifacts();
loadProfiles();
loadLoras();
</script>
</body>
</html>
"""
