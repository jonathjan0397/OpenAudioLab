# Development log

## 2026-10-15 — Repository reset and standalone API backend planning

Author: Codex. Task type: planning and handoff.

Prepared the backend architecture, API contract, model licensing policy, milestone acceptance gates, and implementation-agent instructions for the existing repository. Fixed the public backend boundary at port 50555 and placed lyric generation entirely in the independent frontend's LLM integration. The owner explicitly authorized abandoning and clearing the prior scaffold, reusing `jonathjan0397/OpenAudioLab`. Replace its 157 tracked files with this documentation baseline using a normal commit whose parent is `b272ff2e66e0c00fd3a015afa41333dc63f0c53a`. Previous code and its development log remain in history; Git history is not rewritten.

Created: README.md, AGENTS.md, CODING_AGENT_HANDOFF.md, docs/ARCHITECTURE.md, docs/API_CONTRACT.md, docs/MODEL_POLICY.md, docs/IMPLEMENTATION_PLAN.md, DEVELOPMENT_LOG.md and .gitignore.

Validation: planning-document consistency and required boundary checks only. Application tests, deployment and GPU generation have not run; no application implementation is included.

Next: implementation agent starts milestone 0 on a feature branch. This reset does not rename the repository or change its visibility. Hostname, frontend auth configuration, GPU inventory and actual model benchmarks remain unknown.


## 2026-10-15 — Backend capabilities, required outputs and artist training specification

Author: Codex. Task type: capability planning. User authorized proceeding with the specification after confirming backend-only separation and custom-track artist training.

Created: docs/SERVICE_CATALOG.md, docs/OUTPUT_SPEC.md, docs/ARTIST_TRAINING.md.

Updated: README.md, AGENTS.md, CODING_AGENT_HANDOFF.md, docs/ARCHITECTURE.md, docs/API_CONTRACT.md, docs/MODEL_POLICY.md, docs/IMPLEMENTATION_PLAN.md and this log.

Defined the frontend/backend responsibility boundary and backend service inventory: generation/editing, uploads, project/version data, analysis/DSP/renders, exports, jobs/workers, profiles/datasets/training/evaluation, quotas/usage and administration. Confirmed WAV/MP3 full mixes, aligned WAV stems and ZIP packaging. Separated reference conditioning/style extraction from actual fine-tuning, style from singer identity, active-profile retention from generated-output expiry, and training from inference allocations. Added API shapes and acceptance gates for budgeted real training, evaluation and activation.

Validation: Markdown links/read-order, fenced JSON examples, document inventory, port/lyric/backend-only boundaries, output requirements, training semantics and immutable-profile compatibility reviewed. No application tests, generation, fine-tuning or deployment ran; this commit contains documentation only.

Open decisions: deployment host/TLS, external identity configuration, GPU inventory, verified training base/recipe, measured quality/cost and saved-output retention beyond existing seven-day default. Advanced/model-dependent capabilities remain conditional until proven. No frontend was created and implementation remains pending a coding-agent assignment.


## 2026-10-15 — Docker service topology and model runtime planning

Author: Codex. Task type: architecture planning.

User requires Docker containerization for portable local/cloud deployment. Added docs/CONTAINER_RUNTIME_PLAN.md and aligned README, AGENTS, architecture, model policy, milestones and coding-agent handoff. Specified primary ACE-Step inference/training, isolated HeartMuLa, optional SGLang-Omni MiniMax, dedicated separation/audio/dataset/evaluation workers, private ports, persistence, GPU allocation and Compose profiles. Official ACE-Step docs now provide a headless LoRA/LoKr training path; it remains an untested operational candidate. Final lyrics must bypass upstream text rewriting.

Checks: source documentation reviewed; read-order/port/boundary/runtime consistency checked. No Docker builds, inference, training, cloud provisioning or deployment ran. Remaining gates: pinned compatible image/runtime/checkpoints, exact hardware and real model/training validation.


## 2026-10-15 — Milestone 1: contract-first API on 50555 (implementation start)

Author: opencode. Task type: implementation (feature branch `impl/milestone-1`, not merged).

Owner decisions recorded for this phase: the backend performs no user authentication — the trusted frontend supplies a per-user opaque bearer token which is hashed into an internal owner id used only for resource isolation (documented deviation from the plan's issuer/audience gate); the repository stays private with no source license selected; Vast.ai (North America, cheapest suitable tier) is the planned GPU cloud provider with a small VPS hosting the control plane and manual instance scaling first; containerization is required for quick GPU-cloud scaling, so durable artifacts will live in S3-compatible object storage and remote workers dial out with no shared host paths.

Created: `app/` (FastAPI factory, settings, strict Pydantic schemas, canonical error envelope, request-id and body-limit middleware, exact-origin CORS, static model-release registry stub, bearer-hash owner dependency), durable `jobs` and `idempotency_records` tables with Alembic migration `0001`, `/api/v1` routes for health live/ready, model discovery, job admission (202 + Location, required `Idempotency-Key`, same-key+same-payload replay, 409 on changed payload, ≥24 h retention), owner-scoped cursor-paginated job list, job detail, idempotent cancel, retry (new attempt number), artifacts stub, SSE resync stub and download-url stub. Unknown fields/operations/models/controls fail validation (422); disabled models return 503 and are not queued as ready; lyrics are stored verbatim with SHA-256 over UTF-8 bytes (no trimming or newline normalization); vocal jobs require lyrics and instrumentals forbid them. No inference runs in the API; admitted jobs persist as `queued` until the milestone-2 worker.

Docker: `Dockerfile` (python:3.12-slim, non-root, healthcheck, no GPU/model dependencies), `docker-compose.yml` with `core` profile (api on 50555, one-shot `migrate`, postgres 16, redis 7), `storage` profile (MinIO placeholder; quay.io anonymous pulls may require login or a mirror) and `test` profile placeholder (fixture worker arrives in milestone 2), `.dockerignore`, secret-free `.env.example`, and GitHub Actions CI running pytest on Python 3.12.

Validation: 44 pytest tests pass (ownership isolation across read/list/cancel/retry/artifacts/events, verbatim Unicode lyric round-trip with hash check, concurrent duplicate submit creating one job, 409/422/413/401 cases, CORS preflight allow/deny, OpenAPI route inventory). Live smoke on port 50555 passed locally (SQLite) and through `docker compose --profile core` against PostgreSQL 16 (submit 202, idempotent replay 202, cross-owner 404, api healthy).

Known limits: model revisions are registry stubs until milestone-3 pinning; SSE is a single resync event (polling is the milestone-1 fallback per contract); queue library selection and the outbox/dispatcher arrive in milestone 2; `POST /artifacts/{id}/download-url` returns 404 until assets exist. Next: milestone 2 durable orchestration and the deterministic WAV fixture worker.


## 2026-10-15 — Milestone 2: durable orchestration and the WAV fixture worker

Author: opencode. Task type: implementation (feature branch `impl/milestone-1`, not merged).

Implemented durable orchestration per docs/IMPLEMENTATION_PLAN.md milestone 2. Alembic `0002` adds `job_attempts`, `job_events`, `outbox_records`, `assets` and `workers`, and adds `stage`/`progress`/`progress_source` to `jobs`. Selected the queue mechanism (a milestone-0 open item): plain Redis lists (LPUSH + BRPOP) with database-coordinated claims — at-least-once delivery, no queue-library dependency, and the same primitive a remote Vast.ai worker will use over TLS Redis. Redis is a delivery hint; PostgreSQL records remain authoritative.

Added a separate dispatcher process (`python -m app.dispatcher`) that publishes the outbox (committed rows are marked published so a restart cannot double-publish) and reconciles expired leases (interrupted attempt → requeue with a new attempt number, `failed`/`MAX_ATTEMPTS` when the budget is exhausted, or `cancelled` when cancellation was requested). Added the opt-in deterministic WAV fixture worker (`python -m app.worker`, Compose `test` profile): it claims a queued job with a fenced lease token, heartbeats, generates a deterministic mono 44.1 kHz WAV from the lyrics hash and seed, validates decodability/size, uploads to a private local-filesystem store with server-generated keys, and finalizes one asset labeled `synthetic_test_audio`. Lease fencing rejects stale-lease callbacks; a result arriving after the job left `running` is discarded and cannot publish assets (cancellation beats late completion).

Added short-lived HMAC-signed download URLs (`POST /artifacts/{id}/download-url`) with a `GET /artifacts/{id}/content` byte endpoint supporting HTTP Range (206) and returning 410 after retention; seven-day maintenance (`python -m app.maintenance`) deletes expired output objects idempotently. The API now reports real stage/progress, lists finalized artifact metadata, and replays SSE events with `Last-Event-ID` follow-until-terminal. Compose `core` gains `dispatcher` and `maintenance`; `test` runs the real worker; a shared `artifacts-data` volume is pre-created in the image for the non-root user.

Validation: 58 pytest tests pass (14 new orchestration tests covering outbox creation, no-double-publish, the happy path, download token + Range, cross-owner 404, fixture determinism, duplicate delivery, stale-lease rejection, cancel-beats-late-completion, interrupted recovery, attempt-budget failure, corrupt-artifact rejection, expiry invalidation and SSE replay). Compose `core`+`test` against PostgreSQL 16 + Redis 7 completed submit → dispatch → fixture worker → succeeded, with a decoded WAV verified (mono, 44100 Hz) and 200/206 content responses. Two defects were found and fixed during validation: the shared artifacts volume was root-owned (non-root worker could not write) and the worker swallowed iteration exceptions.

Known limits: the local-filesystem storage adapter is single-host only (the S3-compatible adapter arrives with the real-engine milestone); worker registration is recorded but not yet exposed via an `/internal/v1` API; SSE closes after a bounded follow window with a `resync` hint. Next: milestone 3 — the first real music engine (ACE-Step 1.5) behind an isolated GPU worker, with pinned runtime and license evidence.


## 2026-10-15 — Milestone 3: ACE-Step 1.5 real engine on GPU

Author: opencode. Task type: implementation + hardware validation (feature branch `impl/milestone-1`, not merged).

Closed the milestone-0 deployment facts for the engine: upstream ACE-Step-1.5 pinned at commit `ca1e85f` (2026-08-29), installed with uv in an isolated engine venv (torch 2.10.0+cu128, CUDA 12.8, Python 3.12) on this host's NVIDIA RTX PRO 4000 Blackwell (sm_120, driver 610.57.04, Docker nvidia runtime present). Main checkpoints (ACE-Step/Ace-Step1.5, 28 files) downloaded and size-verified; the HuggingFace transfer stalled twice mid-download and completed via resumable retry. License evidence: MIT code and MIT model card, checked 2026-10-15; registry pinned to revision `1.5.0@ca1e85f` with `license_status=verified`.

Implemented `app/engine_acestep.py` (adapter over the documented /release_task, /query_result, /v1/audio contract; lyrics verbatim with `use_format=false` and CoT disabled in DiT-only mode; native WAV; seed/duration mapped; batch 1) and `app/engine_worker.py` (isolated process: fenced lease claim, poll-as-heartbeat, cancellation by discard since upstream exposes no cancel endpoint, ENGINE_BUSY requeue without burning attempt budget, safe error-code mapping, WAV validation, non-synthetic asset finalize). Admission enforces the upstream 10–600 s duration range. Compose gained the `ace` profile (private `acestep-server` on GPU device 0 with checkpoint volume and healthcheck, plus `engine-worker`) and `Dockerfile.acestep` as the deployment deliverable (image build not yet benchmarked; the host venv is the validated runtime).

Validation on real hardware: cold vocal generation ~10 s (first task initializes the DiT), warm 2–3 s, instrumental 2 s; native output 48 kHz stereo WAV (5,760,078 bytes for 30 s) decoded and delivered through the public API with 200/206 Range responses; VRAM ~12.3 GB DiT-only on GPU 0. Two full pipeline jobs (API → dispatcher → engine worker → API) succeeded on PostgreSQL 16 + Redis 7 with attempt 1 and zero worker errors after the fix below. pytest: 68 passed (10 new engine tests).

Defect found and fixed during validation: redis-py >=6 defaults socket_timeout to 5 s, which raced the 5 s blocking BRPOP and spammed worker iteration timeouts; the queue factory now pins socket_timeout=None with a 30 s health check, and the redis dependency is held at the pinned 5.* line. Compose also gained loopback port mappings for PostgreSQL/Redis so host-side workers can reach them.

Known limits: DiT-only configuration (thinking=false; the 5Hz LM planning mode remains untested here); MP3/stem exports are milestone 4; upstream cancellation is discard-only; OOM handling maps upstream failures but was not force-injected. Next: milestone 4 — backend audio services (projects/versions, uploads, WAV/MP3/stem exports via a CPU audio worker) and external frontend contract tests.


## 2026-10-15 — Milestone 4: backend audio services + frontend contract

Author: opencode. Task type: implementation + live validation (feature branch `impl/milestone-1`, not merged).

Implemented the milestone-4 service slice on Alembic `0003` (projects, project_versions, upload_sessions; assets gained `kind`/`source_asset_id`/`stem_source`/`stem_category`/`processing` and a nullable `job_id`; SQLite compatibility via batch mode). Projects: owner-scoped CRUD with tombstone delete and integer-ETag optimistic concurrency — PATCH/restore require `If-Match` (428 missing, 412 mismatch), every mutation bumps the revision. Versions are immutable, created from a succeeded job's `mix_wav` asset or an uploaded asset, and carry a frozen manifest (asset checksum, format, model revision, lyrics hash); restore moves the active pointer. Uploads: allocate session → PUT raw bytes (route-level size cap) → complete probes with the stdlib WAV reader and FFmpeg fallback, failing closed (`UPLOAD_NOT_AUDIO`); `GET`/`DELETE /assets/{id}` read and revoke (410 after). Exports: `POST /exports` validates the owned immutable version and settings before queuing (native-only WAV, PCM16, MP3 128/192/256/320 — unsupported values rejected, never silently dropped) and queues an `audio.export` job on `oal:queue:audio-export`; the CPU audio worker produces `mix_wav` (native copy), `mix_mp3` (FFmpeg libmp3lame with codec and ±20% bitrate validation via ffprobe), `stems_wav` (explicit Demucs `htdemucs` subprocess in the engine venv; stems labeled `separated`, sample-alignment validated across the package) and `stems_zip` (server-generated names + manifest.json); per-output failure preserves usable assets as partial results without overall success.

Environment facts recorded: demucs installed into the pinned engine venv via bootstrapped pip (uv had vanished from PATH) with torchaudio 2.10.0+cu128 from the cu128 index to match torch; host FFmpeg 6.1.1 present and added to the API image; compose gained an `audio-worker` service in the `ace` profile (stems fail closed with `SEPARATOR_UNAVAILABLE` unless `OAL_DEMUCS_PYTHON` points at a separator runtime).

Validation: pytest 83 passed (15 new). Live contract run (`scripts/frontend_contract.py`, stdlib-only, framework-agnostic): health/discovery → real vocal job (12 s, seed 42) → 2,304,078-byte 48 kHz stereo WAV with signed URL + Range 206 → project/version/ETag (412 on stale If-Match) → export job succeeded attempt 1 → MP3 measured 320,029 bps / 12.02 s by ffprobe, four identical-size separated stems (`demucs-htdemucs`), ZIP with 4 stems + manifest. Two defects found and fixed during live runs: the live PostgreSQL had not received `0003` (tests used a fresh SQLite file) — applied; and the contract script double-prefixed `/api/v1` on signed URLs.

Known limits: WAV export is native-only (conversions rejected pre-queue); containerized audio worker needs a separator runtime; demucs runs CPU-side (GPU optional); analysis/processing recipes and artist profiles are milestone 5+. Next: milestone 5 — artist profiles/training foundation or operations hardening, per the service catalog.
