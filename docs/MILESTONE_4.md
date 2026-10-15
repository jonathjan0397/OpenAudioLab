# Milestone 4 — Backend audio services and external frontend integration

Status: **complete** on branch `impl/milestone-1` for the local stack.
Not merged to `master`; not deployed. Date: 2026-10-15.

## Scope delivered

- **Projects and versions** (`app/routes/projects.py`, Alembic `0003`):
  owner-scoped projects with tombstone delete; immutable versions created from
  a succeeded job's mix asset or an uploaded asset; restore moves the active
  pointer. Optimistic concurrency via integer ETag: PATCH/restore require
  `If-Match` (428 missing, 412 mismatch); every mutation bumps the revision.
- **Asset ingestion** (`app/routes/uploads.py`): allocate session → PUT raw
  bytes → complete runs the probe (stdlib WAV reader, FFmpeg fallback) and
  finalizes an `uploaded` asset with real metadata. Non-audio fails closed
  (`UPLOAD_NOT_AUDIO`); oversize is 413; `GET`/`DELETE /assets/{id}` read and
  revoke (410 after revoke).
- **Exports** (`app/routes/exports.py`, `app/audio_worker.py`):
  `POST /exports` validates the owned immutable source version and the
  requested settings before queuing (unsupported WAV rate/encoding and MP3
  bitrate rejected pre-queue; outputs never silently dropped), then queues an
  `audio.export` job on its own queue (`oal:queue:audio-export`). The CPU
  audio worker produces `mix_wav` (native copy), `mix_mp3` (FFmpeg libmp3lame
  with codec/bitrate validation), `stems_wav` (explicit separation operation)
  and `stems_zip` (safe server-generated names + manifest). Per-output
  failures preserve usable assets as partial results without overall success.
- **Stem separation** (`app/separator.py`): Demucs `htdemucs` subprocess
  adapter in the engine venv (torchaudio 2.10.0+cu128 installed alongside the
  pinned torch). Stems are labeled `stem_source=separated` with the separator
  revision in `processing`; sample alignment is validated across the package
  (same rate/channels/sample count). No separator configured fails closed
  (`SEPARATOR_UNAVAILABLE`) — separated stems are never implied native.
- **Lineage columns** on assets: `kind` (generated/uploaded/exported),
  `source_asset_id`, `stem_source`, `stem_category`, `processing`; artifacts
  responses expose them.
- **Frontend contract demonstration** (`scripts/frontend_contract.py`):
  stdlib-only script (no framework) exercising discovery → submission →
  polling → signed download with Range → project/version/ETag → export →
  delivery. Compose gained an `audio-worker` service in the `ace` profile and
  the API image now carries FFmpeg 6.1.

## Live contract evidence (this host, real engine + real separator)

`scripts/frontend_contract.py` against the running stack (PostgreSQL 16 +
Redis 7 + host API/dispatcher/engine worker/audio worker + ACE-Step server):

| Step | Result |
| --- | --- |
| Health + model discovery | pass |
| Vocal job (12 s, seed 42) | succeeded; 2,304,078-byte 48 kHz stereo WAV |
| Signed download + Range | full 200 + ranged 206 (100 bytes) |
| Project + immutable version | manifest carries model revision + lyrics hash |
| Optimistic concurrency | stale If-Match → 412; correct If-Match → 200, new ETag |
| Export (mix_mp3 + stems_wav + stems_zip) | succeeded on attempt 1 |
| MP3 | ffprobe: 320,029 bps, 12.02 s (requested 320 kbps) |
| Stems | 4 WAVs, identical size (aligned), `separated`, `demucs-htdemucs` |
| ZIP | 4 stems + manifest.json, server-generated names |

## Acceptance gates

| Gate (docs/IMPLEMENTATION_PLAN.md) | Result | Evidence |
| --- | --- | --- |
| Contract tests against the configured origin on 50555 | Pass | 83 pytest + live contract script |
| Final lyrics submitted without any lyrics LLM | Pass | lyrics verbatim through generation (M3) |
| Private Range delivery + signed expiring URL refresh | Pass | 206 + token expiry paths |
| WAV/MP3 export settings verified | Pass | native copy + 320 kbps ffprobe |
| Identical source version for mixes | Pass | both mixes derive from the frozen version asset |
| Stem sample alignment | Pass | worker validates equal rate/channels/sample count |
| ZIP contents + metadata | Pass | names + manifest asserted live |
| Upload probe validation | Pass | garbage → 422; WAV metadata recorded |

## Validation run

- `pytest tests -q` → 83 passed (15 new audio-service tests).
- Live contract demo: `CONTRACT OK` (table above).
- Migration `0003` applied to the live PostgreSQL (batch mode keeps SQLite
  compatible).

## Known limits / deferred

- WAV export is native-only by design this milestone; 44.1/48 kHz and PCM24
  conversions are rejected pre-queue (`EXPORT_SETTING_UNSUPPORTED`), not
  silently ignored.
- The containerized audio worker needs a separator runtime
  (`OAL_DEMUCS_PYTHON`); without it stem exports fail closed. The validated
  runtime is the host engine venv (same policy as the M3 engine).
- Demucs runs on CPU in the audio worker; GPU separation is a deployment
  option (`OAL_DEMUCS_DEVICE=cuda:N`).
- Analysis (peaks/loudness) and processing recipes are later milestones;
  uploads currently store probe metadata only.
- Webhooks, quotas/entitlements and artist profiles remain per the service
  catalog (milestone 5+).
