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

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..models import Asset, utcnow
from ..orchestration import as_utc
from ..schemas import GenerateJobRequest
from ..tokens import make_token
from .jobs import _get_owned_job, create_job

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
    gen = GenerateJobRequest(**body)
    shim = _RequestShim(request.app, {"Idempotency-Key": f"lab-{uuid4().hex}"})
    return create_job(gen, shim, _lab_owner(settings.lab_owner_token))


@router.get("/lab/api/jobs/{job_id}")
def lab_job(
    job_id: str,
    request: Request,
    _: HTTPBasicCredentials = Depends(require_lab),
) -> JSONResponse:
    settings = request.app.state.settings
    owner = _lab_owner(settings.lab_owner_token)
    with request.app.state.db.session() as session:
        job = _get_owned_job(session, job_id, owner)
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
    <div style="margin-top:16px"><button id="go">Generate</button></div>
    <div class="status" id="status"></div>
    <div class="result" id="result"></div>
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
const $ = (id) => document.getElementById(id);
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])) ;
const fmtTime = (iso) => { if (!iso) return ""; const d = new Date(iso); return isNaN(d) ? "" : d.toLocaleString(); };
const fmtDur = (s) => (s == null ? "" : (Math.round(s * 10) / 10) + "s");

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (res.status === 401) { setStatus("Authentication failed - reload and re-enter credentials."); return null; }
  return res;
}

function setStatus(t) { $("status").textContent = t || ""; }

function audioBlock(a) {
  const expired = a.expired ? ' <span class="tag">expired</span>' : "";
  const synth = a.synthetic ? ' <span class="tag">synthetic</span>' : "";
  return '<div class="art"><div class="meta">'
    + '<span class="tag">' + esc(a.role || "audio") + '</span>'
    + '<span>' + fmtDur(a.duration_seconds) + '</span>'
    + '<span>' + (a.bytes ? Math.round(a.bytes / 1024) + " KB" : "") + '</span>'
    + '<span>' + esc(fmtTime(a.created_at)) + '</span>' + expired + synth
    + '</div><audio controls preload="none" src="' + esc(a.url) + '"></audio></div>';
}

async function loadArtifacts() {
  const res = await api("/lab/api/artifacts?limit=50");
  if (!res) return;
  const data = await res.json();
  const items = data.artifacts || [];
  $("list").innerHTML = items.length
    ? items.map(audioBlock).join("")
    : '<li class="empty">No audio artifacts yet - generate one above.</li>';
}

let pollTimer = null;
async function pollJob(jobId) {
  const res = await api("/lab/api/jobs/" + encodeURIComponent(jobId));
  if (!res) return;
  const job = await res.json();
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
  pollTimer = setTimeout(() => pollJob(jobId), 2000);
}

async function generate() {
  if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  const body = {
    music_description: $("desc").value.trim(),
    duration_seconds: $("dur").value ? parseInt($("dur").value, 10) : null,
    instrumental: $("inst").checked,
    model_id: "ace-step-1.5",
  };
  if (!$("desc").value.trim()) { setStatus("Enter a description first."); return; }
  if ($("seed").value !== "") body.seed = parseInt($("seed").value, 10);
  $("go").disabled = true; $("result").innerHTML = ""; setStatus("Submitting...");
  const res = await api("/lab/api/generate", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res) { $("go").disabled = false; return; }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    setStatus("Rejected: " + ((err.error && err.error.code) || res.status));
    $("go").disabled = false; return;
  }
  const data = await res.json();
  setStatus("Queued " + (data.job_id || "").slice(0, 8) + "...");
  pollJob(data.job_id);
}

$("go").addEventListener("click", generate);
$("refresh").addEventListener("click", loadArtifacts);
loadArtifacts();
</script>
</body>
</html>
"""
