# Changelog

All notable changes to the OpenAudioLab backend implementation. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Implementation lives on
feature branches; `master` remains the documentation/planning baseline until the
owner approves a merge. Per-milestone acceptance records are in `docs/MILESTONE_N.md`.

## [Unreleased]

### Remote worker deployments (ephemeral GPU nodes over WireGuard)
- S3-compatible object storage adapter (`S3ObjectStorage` + `build_storage`
  factory, `OAL_STORAGE_BACKEND=local|s3` + `OAL_S3_*`, `boto3`) as the durable
  cross-host store; all six services build storage via the factory; the API
  proxies ranged reads so the bucket stays private.
- Worker code bundle endpoint `GET /internal/v1/worker/bundle` (tar.gz of `app/`
  + `REVISION`, `X-OAL-Revision` header): an ephemeral node pulls its code from
  the backend over the tunnel, so the heavy runtime image stays generic.
- Cross-host adapter persistence: training uploads the exported PEFT files to
  object storage (object prefix + file list in `artifacts_json`); the engine
  worker downloads them to a node-local cache before `load_lora`, so a profile
  trained on one node generates on another.
- Combined worker image `stratastack/oal-worker:ca1e85f-torch2.10-cu128`
  (`Dockerfile.worker` + `docker/worker-entrypoint.sh`) built and pushed to
  Docker Hub; `docker-compose.worker.yml`, `.env.worker.example` and
  `deploy/wireguard/worker-peer.conf.template` for the node.
- Validation: the pushed image ran as a container (no shared volume), fetched
  its bundle over HTTP, generated, pushed the WAV to S3 and the API served it
  (200, valid RIFF, 2,304,044 bytes). 6 new tests (99 total). Record:
  `docs/REMOTE_WORKERS.md`.

### Baseline fallback and standard OAL LLM (2026-10-19)
- Worker health and stable identity: `OAL_WORKER_ID`, `Worker.last_error`,
  `Worker.unhealthy_until`, Alembic `0026`, OOM/unhealthy marking, and stable
  baseline/audio/training worker ids.
- Autoscaler baseline fallback: health-checks `OAL_BASELINE_WORKER_ID`, creates a
  North-American fallback node after 5 minutes of baseline unavailability, runs
  it as `OAL_WORKER_TIER=baseline` on the main queue, and destroys it 5 minutes
  after baseline restoration.
- Standard OAL LLM: Qwen3-4B Q4_K_M GGUF baked into the worker image and served
  by `llama.cpp`; `/llm/draft` and lyrics-write use hybrid thinking, while
  humanize/style/title do not. The autoscaler publishes the active LLM endpoint
  to `site_settings.llm_base_url` and restores `OAL_PRIMARY_LLM_BASE_URL`.
- Validation: full pytest suite passes (203 tests). Live fallback test created
  Vast contract `56795630`, switched LLM endpoint to the fallback node, completed
  all LLM routes and generation job `e2b1d3fc-7a55-4268-80ae-5f10e9939ceb`, then
  restored the baseline endpoint and destroyed the fallback.

### House LoRA merge A/B (2026-10-20)
- Added offline ACE-Step merge/A-B tooling: `scripts/house_merge_ab.py`,
  `scripts/house_merge_ab_agent.sh`, `Dockerfile.house_merge`,
  `curation/house_ab_prompts.json`, and `curation/house_ab_prompts_test.json`.
- Corrected multi-LoRA merge semantics after the first full A/B sounded
  unrecognizable: ACE-Step runtime LoRA scale is a 0–1 multiplier on the active
  PEFT adapter, so the first raw `linear` run with 13 adapters at `0.30`
  effectively applied about `3.9x` total LoRA strength.
- The corrected merge uses PEFT `combination_type=cat` with normalized weights,
  so `0.30`, `0.50`, and `0.70` are total merge strengths across all 13 house
  LoRAs rather than per-LoRA strengths.
- Ran a one-adapter sanity merge (`house-v1-pop`, scale `0.30`) and a corrected
  full A/B on Vast RTX 3090 nodes. Results are retained locally under
  `/Cold-Archive/OpenAudioLab/house-lora-ab/2026-10-19-one-pop/` and
  `/Cold-Archive/OpenAudioLab/house-lora-ab/2026-10-19-v2/`.
- Fully documented the LoRA training and model merge processes in
  `docs/HOUSE_LORA_TRAINING.md`.
- Promoted the `house_070` merged checkpoint to the production default as
  `acestep-v15-house-turbo`: baked into worker image
  `stratastack/oal-worker:house-v1-070` (`Dockerfile.house_worker`), baseline
  worker recreated on it, and the autoscaler + hub `.env.backend` now pass
  `ACESTEP_CONFIG_PATH`/`OAL_ACESTEP_MODEL=acestep-v15-house-turbo` to generation
  nodes. `acestep-v15-turbo` remains available for rollback.

### Generation contract + ACE-Step parity audit (2026-10-20)
- Fixed the generation-submission blocker (`HTTP 422 CONTROL_UNSUPPORTED`): free-text song
  idea and style direction are no longer placed in the engine `controls` bag. The shared
  creator mutation (`frontend/src/components/CreateWidget.tsx`) now uses a canonical
  serializer (`frontend/src/lib/generation.ts`) that keeps idea, raw style, and the resolved
  non-lyric caption independent and emits only registry-supported controls. Incorporates the
  intent of PR #1 (`1332528e`) without reverting newer work.
- Added first-class typed metadata `song_idea` and `style_prompt` to `GenerateJobRequest`
  (`app/schemas.py`); persisted in the recipe and read by Studio recreation with a legacy
  fallback.
- Corrected lyrics provenance (`human` vs `frontend_llm` instead of always `frontend_llm`)
  and preserved exact, untrimmed approved lyrics in the frontend payload.
- Folded the lead-singer preference into the non-lyric caption (the adapter has no gender
  field) and relabeled the misnamed "Weirdness" slider to "Timestep Shift", disabled for the
  Turbo model (upstream: shift only affects base checkpoints).
- Frontend error handling now keeps a typed safe envelope (`ApiError`) exposing
  `code`, `request_id`, `unknown_controls`, and `supported_controls`, with an actionable
  hint and no leak of request bodies/paths.
- Added `docs/ACE_STEP_CONTROL_PARITY.md` (audited against pinned `ca1e85f`
  `release_task_models.GenerateMusicRequest`) and `docs/CAPABILITY_MATRIX.md`.
- Tests: `tests/test_generation_contract.py` proves unsupported free-text controls are still
  rejected with field details and reserve no work, and that the corrected payload with
  independent metadata is admitted. Backend 206 passed; frontend build green.
- Scope note: real remix / vocal / melody / repaint / extract / lego / complete (3A) and the
  full advanced control bridge (3B/3C) remain **not-wired / engine-blocked** and are not
  claimed complete.

## [Milestone 5] - 2026-10-15

Artist profiles and real LoRA fine-tuning on hardware. Branch
`impl/milestone-1`. Record: `docs/MILESTONE_5.md`.

### Added
- Artist schema (Alembic `0004`): `artist_profiles`, `rights_records`,
  `datasets`/`dataset_tracks`/`dataset_versions`, `artist_profile_versions`,
  `training_runs`, `evaluations`; immutable versions with mechanism, base
  revision, recipe, dataset version, evaluation status and activation state.
- Artist API (`app/routes/artist.py`): owner-scoped profiles with ETag,
  rights declarations, dataset track add + `finalize` (train/validation/holdout
  split by recording unit + `frozen_sha256`), `trainings` with pre-queue
  budget validation (`BUDGET_EXCEEDED`), `evaluations`, `activate` (409
  `PROFILE_NOT_EVALUATED` until measured) and `review`.
- Training adapter (`app/training_acestep.py`) over the upstream ACE-Step
  training REST contract (`/v1/init`, dataset scan/preprocess, training
  start/status/stop/export, LoRA load/unload/toggle) and an isolated training
  worker (`app/training_worker.py`) on `oal:queue:training`/`oal:queue:evaluation`
  with fenced leases, heartbeat, cancellation, budget guard and candidate
  registration (recipe `acestep-lora@ca1e85f`).
- Profile-aware generation: admission resolves the active profile version
  (`PROFILE_INCOMPATIBLE`/`PROFILE_VERSION_NOT_FOUND`); the engine worker loads
  the candidate LoRA per job. Compose `training-worker` service;
  `scripts/training_cycle.py` live gate driver.
- 10 new artist/training tests (93 total).

### Evidence
- Live custom-track cycle on an RTX PRO 4000 Blackwell: 3 generations → dataset
  frozen → LoRA training (24.0 s) → candidate `fine_tuned_adapter` registered →
  evaluation (6.0 s, `measured`) → activation → generation with the active
  profile; activated version `adapter_loadable=true`, final loss 1.2937.

## [Milestone 4] - 2026-10-15

Backend audio services and external frontend integration. Branch
`impl/milestone-1`. Record: `docs/MILESTONE_4.md`.

### Added
- Projects with owner-scoped CRUD, tombstone delete and integer-ETag
  optimistic concurrency (`If-Match` required on PATCH/restore; 428 missing,
  412 mismatch); immutable project versions created from a succeeded job's mix
  asset or an uploaded asset; restore moves the active pointer.
- Asset ingestion: upload session allocate → PUT bytes → complete with probe
  (stdlib WAV reader, FFmpeg fallback); non-audio fails closed
  (`UPLOAD_NOT_AUDIO`); `GET`/`DELETE /assets/{id}` with 410 after revoke.
- Export jobs (`POST /exports`, `audio.export` operation, dedicated queue):
  settings validated before queuing (native-only WAV, MP3 128/192/256/320);
  CPU audio worker publishes `mix_wav` native copy, `mix_mp3` (FFmpeg
  libmp3lame, codec + bitrate validation), `stems_wav` (explicit Demucs
  `htdemucs` separation, sample-alignment validated, `stem_source=separated`)
  and `stems_zip` (safe names + manifest). Partial results preserved on
  per-output failure.
- Asset lineage: `kind`, `source_asset_id`, `stem_source`, `stem_category`,
  `processing` (Alembic `0003`, SQLite-batch compatible).
- `scripts/frontend_contract.py`: stdlib-only frontend contract demonstration
  (discovery → submit → poll → signed download + Range → project/version/ETag
  → export → delivery).
- Compose `audio-worker` service in the `ace` profile; API image now includes
  FFmpeg 6.1; engine venv gained demucs + torchaudio 2.10.0+cu128.
- 15 new tests (83 total).

### Evidence
- Live contract run on the real stack: vocal job (12 s, seed 42) → 48 kHz
  stereo WAV delivered with 200/206; export produced a 320,029 bps MP3
  (ffprobe) and four sample-aligned separated stems + ZIP with manifest.

## [Milestone 3] - 2026-10-15

First real music engine: ACE-Step 1.5 behind an isolated GPU worker. Branch
`impl/milestone-1`. Record: `docs/MILESTONE_3.md`.

### Added
- ACE-Step 1.5 adapter over the documented upstream REST contract
  (`/release_task`, `/query_result`, `/v1/audio`) with lyrics passed verbatim
  (`use_format=false`; CoT disabled in DiT-only mode) and native WAV output.
- Engine worker process with fenced leases, poll-as-heartbeat, cancellation by
  discard (upstream has no cancel endpoint), `ENGINE_BUSY` requeue without
  budget burn, and safe error codes (`ENGINE_REJECTED`, `ENGINE_AUTH`,
  `ENGINE_BUSY`, `ENGINE_GENERATION_FAILED`, `ENGINE_TIMEOUT`,
  `ENGINE_NO_AUDIO`, `ARTIFACT_INVALID`).
- Pinned runtime: upstream commit `ca1e85f`, torch 2.10.0+cu128 (CUDA 12.8),
  Python 3.12, uv-managed; checkpoints size-verified. Registry revision
  `1.5.0@ca1e85f`, license `verified` (MIT code + MIT model card).
- Admission now enforces the model duration range (10–600 s) and model detail
  reports `min_duration_seconds`.
- Compose `ace` profile (private `acestep-server` with GPU device 0 +
  `engine-worker`) and `Dockerfile.acestep` deployment deliverable.
- 10 new engine tests (68 total).

### Fixed
- Redis blocking reads: redis-py >=6 defaults `socket_timeout=5s`, racing the
  5 s BRPOP; the queue factory pins `socket_timeout=None` with a health check
  and the dependency is held at the `5.*` line.
- Compose exposes PostgreSQL/Redis on loopback ports for host-side workers.

### Evidence
- Real vocal and instrumental generation on an RTX PRO 4000 Blackwell: cold
  ~10 s, warm 2–3 s, ~12.3 GB VRAM (DiT-only); 48 kHz stereo WAV delivered
  through the public API with Range support; `synthetic_test_audio=false`.

## [Milestone 2] - 2026-10-15

Durable orchestration and the deterministic WAV fixture worker. Branch
`impl/milestone-1`. Record: `docs/MILESTONE_2.md`.

### Added
- Durable `job_attempts`, `job_events`, `outbox_records`, `assets` and `workers`
  tables (Alembic `0002`); `jobs` gains `stage`, `progress`, `progress_source`.
- Redis list delivery (LPUSH + BRPOP) with database-coordinated claims; the
  database remains the authoritative job truth.
- Dispatcher process: outbox publication (no double-publish after restart) and
  lease reconciliation (interrupted → requeue, `MAX_ATTEMPTS` failure, or
  cancellation).
- Opt-in deterministic WAV fixture worker producing `synthetic_test_audio`
  artifacts with fenced lease tokens and heartbeats.
- Lease fencing and completion guards: stale-lease callbacks are rejected; a
  late result after cancellation is discarded and cannot publish assets.
- Private local-filesystem storage with server-generated keys; assets carry
  role, MIME, bytes, SHA-256, audio metadata, synthetic flag and seven-day
  expiry.
- Short-lived HMAC-signed download URLs with HTTP Range (206) support and 410 on
  expired retention; seven-day maintenance cleanup deletes expired objects.
- SSE replays persisted events with `Last-Event-ID` and follows to a terminal
  state; job detail reports real stage/progress.
- Compose `core` gains `dispatcher` and `maintenance`; `test` runs the real
  fixture worker; shared `artifacts-data` volume.
- 14 new pytest orchestration tests (58 total).

### Fixed
- The shared `artifacts-data` volume is pre-created in the image so the non-root
  container user can write; the worker now logs swallowed exceptions.

## [Milestone 1] - 2026-10-15

Contract-first API and identity. Branch `impl/milestone-1`, commits `0fad838`,
`69ae50d`. Record: `docs/MILESTONE_1.md`.

### Added
- FastAPI application factory on port 50555 under `/api/v1` (no model weights or
  CUDA dependencies in the API image).
- Canonical error envelope `{error: {code, message, request_id, details}}`;
  `X-Request-ID` correlation; request body size limit (413).
- Exact-origin CORS allowlist with `Authorization`, `Content-Type`,
  `Idempotency-Key`; exposes `Location`, `Retry-After`, `X-Request-ID`.
- Model discovery: `GET /models`, `GET /models/{model_id}` from a static
  model-release registry stub (ACE-Step 1.5 enabled; HeartMuLa, MiniMax Music 3,
  DiffRhythm 2, YuE v1 listed disabled).
- Job admission `POST /jobs` (202 + `Location`): strict discriminated validation,
  required `Idempotency-Key` (same key + same payload replays the original 202;
  same key + different payload returns 409; keys retained at least 24 hours).
- Owner-scoped job reads and lifecycle: cursor-paginated `GET /jobs`,
  `GET /jobs/{id}`, idempotent `POST /jobs/{id}/cancel`, `POST /jobs/{id}/retry`
  (new attempt number), `GET /jobs/{id}/artifacts` stub, SSE resync stub,
  `POST /artifacts/{asset_id}/download-url` stub.
- Durable `jobs` and `idempotency_records` tables with Alembic migration `0001`;
  UTC timestamps; owner id derived only from the bearer credential.
- Lyrics preserved verbatim (no trimming or newline normalization) with
  SHA-256 over UTF-8 bytes; vocal jobs require lyrics, instrumentals forbid them;
  unknown fields/operations/models/controls rejected (422); disabled models
  return 503 and are never queued as ready.
- Docker: `Dockerfile` (python:3.12-slim, non-root, healthcheck),
  `docker-compose.yml` with `core` (api, one-shot migrate, postgres 16, redis 7),
  `storage` (MinIO placeholder) and `test` (fixture worker placeholder) profiles,
  `.dockerignore`, secret-free `.env.example`.
- GitHub Actions CI running pytest on Python 3.12.
- 44 pytest acceptance tests; live smoke on 50555 against SQLite and against
  PostgreSQL 16 through Compose.

### Changed
- Owner decisions recorded: backend performs no user authentication (trusted
  frontend supplies an opaque per-user bearer token, hashed to an internal owner
  id); repository stays private with no source license selected; Vast.ai (North
  America, cheapest suitable tier) is the planned GPU cloud provider with a
  small VPS control plane and manual scaling first.

## [Planning baseline] - 2026-10-15

- Repository reset to documentation baseline (v0.3-container-plan): capability
  specification, API contract, model policy, milestones, container runtime plan
  and coding-agent handoff. No implementation.
