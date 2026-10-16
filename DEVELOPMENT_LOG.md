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


## 2026-10-15 — Milestone 5: artist profiles + real LoRA fine-tuning

Author: opencode. Task type: implementation + hardware validation (feature branch `impl/milestone-1`, not merged).

Implemented the artist-training foundation on Alembic `0004` (artist_profiles, rights_records, datasets/dataset_tracks/dataset_versions, artist_profile_versions, training_runs, evaluations). The artist API (`app/routes/artist.py`) exposes owner-scoped profiles with integer-ETag concurrency, rights declarations (evidence records, not ownership proof), datasets whose `finalize` assigns each recording to train/validation/holdout (split by recording unit to avoid evaluation leakage) and freezes a `frozen_sha256`, trainings with pre-queue budget validation (`BUDGET_EXCEEDED`), evaluations, and activation that returns 409 `PROFILE_NOT_EVALUATED` until a version is `measured`, keeping the previous active version for rollback. `app/training_acestep.py` adapts the upstream ACE-Step training REST contract (`/v1/init`, dataset scan/preprocess, training start/status/stop/export, LoRA load/unload/toggle); `app/training_worker.py` is an isolated process on `oal:queue:training`/`oal:queue:evaluation` with fenced leases, poll-as-heartbeat, cancellation, a budget guard and candidate registration under recipe `acestep-lora@ca1e85f`. Generation became profile-aware: admission resolves the active profile version (`PROFILE_INCOMPATIBLE`/`PROFILE_VERSION_NOT_FOUND`) and the engine worker loads the candidate LoRA for the job and unloads after. Compose gained a `training-worker` service and `scripts/training_cycle.py` drives the live gate.

Upstream integration findings from real hardware: the training path-safety root is the server working directory, so `OAL_TRAIN_WORKDIR` must live under the engine checkout; the trainer nests PEFT output at `lora/final/adapter/` (the worker resolves it); upstream keeps adapter names registered after unload, so every load uses a unique `adapter_name` and unloads first, and the base-vs-candidate evaluation toggles `use_lora` rather than unload/reload; the DiT lazy-loads on first generation, so the worker calls `/v1/init` before preprocessing. A test-harness pitfall was also corrected: `pkill -f app.training_worker` self-matches the invoking shell's own command line and must use the `[a]` bracket form.

Validation on real hardware: `scripts/training_cycle.py` completed a full custom-track cycle (`TRAINING CYCLE OK`) — three generations as training material, dataset frozen, LoRA training in 24.0 s, candidate `fine_tuned_adapter` registered, evaluation in 6.0 s (`measured`), activation, and a generation that loaded the active profile's adapter. The activated version reports `adapter_loadable=true` with final loss 1.2937 on `ai-server01`. pytest: 93 passed (10 new artist/training tests). Migration `0004` applied to the live PostgreSQL.

Known limits: dataset finalize records segmentation/transcription/stem preparation as annotations but does not run them; budgets are simple pre-queue caps (max epochs / wall-clock) without reservation/settlement accounting; resume/checkpoint-restart is not implemented and training auto-retry is off; evaluation is fixed-prompt candidate-vs-base samples plus owner review (no automatic quality score); training and inference share the single validated host GPU here. Next: operations hardening (observability, quotas/entitlements, retention) or the frontend business site, per the service catalog.


## 2026-10-15 — Remote worker deployments (ephemeral GPU nodes over WireGuard)

Author: opencode. Task type: implementation + deployment validation (feature branch `impl/milestone-1`, not merged).

Planted the remote worker deployment model: temporary GPU nodes (Vast.ai) dial out to the backend hub over WireGuard (no inbound ports on NAT'd instances), pull a prebuilt image, fetch their application code from the backend at boot, and push every result back to backend object storage — nothing durable lives on the node, and the ACE-Step engine server is co-located on the node (worker→engine is localhost). Implemented the cross-host prerequisite, the S3-compatible object-storage adapter (`S3ObjectStorage` + a `build_storage` factory selected by `OAL_STORAGE_BACKEND`, `OAL_S3_*` settings, `boto3`), replacing the six direct `LocalObjectStorage` sites behind a small `Storage` protocol; the API proxies ranged reads so the bucket stays private. Added the worker code bundle endpoint `GET /internal/v1/worker/bundle` (tar.gz of `app/` + a `REVISION` file, `X-OAL-Revision` header) so the container pulls its code over the tunnel and the backend is the source of truth for the worker code revision. Made trained adapters portable across hosts: the training worker uploads the exported PEFT files to object storage (object prefix + file list in `artifacts_json`) and the engine worker downloads them to a node-local cache before `load_lora`.

Built a single combined worker image (`Dockerfile.worker` + `docker/worker-entrypoint.sh`: pinned ACE-Step runtime + our deps; the entrypoint fetches the bundle, starts the co-located ACE-Step server, then the worker role(s)) and pushed it to Docker Hub as `stratastack/oal-worker:ca1e85f-torch2.10-cu128` (the `openaudiolab` namespace was not writable by the `stratastack` PAT account). Added `docker-compose.worker.yml`, `.env.worker.example` and `deploy/wireguard/worker-peer.conf.template`.

Environment facts: the dev host is a WireGuard client on the existing "Simple Server Networks" mesh (`10.201.0.0/24`, hub mercury), NAT'd behind a router with a public IP; Docker Hub anonymous pulls on this host are rate-limited (MinIO's `latest` is retired and the repo would not resolve), so local validation used `moto_server` as the S3 endpoint. Validation: the pushed image ran as a container (GPU, host network, S3/DB/Redis/bundle at the hub, no shared artifacts volume), fetched its code bundle over HTTP (revision `99c2999`), generated a real vocal job, pushed the WAV to S3 at an owner-scoped key, and the API served it (200, valid RIFF, 2,304,044 bytes) — proving the full remote-worker mechanism (image pull, container-initiated code transfer, S3 push-back, delivery) without a shared host path. pytest: 99 passed (6 new).

Known limits: admitting a new node peer depends on the mercury hub routing (a dedicated VPS hub makes this plain hub-and-spoke); production runs MinIO on the hub (moto_server was validation-only); the combined container supervises server+workers with a simple `wait` (a full process supervisor is later hardening); checkpoints download-to-volume on first boot. Next: provision a real Vast.ai node over the tunnel as the capstone, then operations hardening (observability, quotas, retention) or the frontend business site.


## 2026-10-16 — Home-server dev migration + Vast.ai end-to-end (public-IP hub)

Author: opencode. Task type: deployment migration + real-cloud validation (feature branch `impl/milestone-1`, not merged).

Migrated development to the home server: cloned `impl/milestone-1` to `~/OpenAudioLab`, installed `python3-venv`, created a test venv and confirmed **99 passed** there (the home server is now the dev host; `ai-server01` is reduced to a remote worker). Made the worker entrypoint self-sufficient for cloud nodes: when `OAL_WG_UP=1` and no `wg0.conf` is mounted it now writes `/etc/wireguard/wg0.conf` from env (`OAL_WG_PRIVKEY/ADDRESS/PUBKEY/ENDPOINT`), so a bind-mount-free container can bring its own tunnel up; rebuilt and pushed `stratastack/oal-worker:ca1e85f-torch2.10-cu128-wg`.

Provisioned a real Vast.ai on-demand node (cheapest North-American Blackwell, RTX 5060 Ti 16 GB, ~$0.13–0.17/hr) and completed a full generation end-to-end against the home-server hub. Two hard constraints surfaced and changed the transport: (1) **Vast containers lack `NET_ADMIN`** — `ip link add wg0 type wireguard` returns `Operation not permitted`, and neither `--cap-add NET_ADMIN` nor `--privileged` via the CLI `--env` string grants it, so in-container WireGuard is not usable on Vast; (2) **Vast's default launch mode requires an `ssh` binary** the image lacks (it loops on `ssh: command not found` and never runs the entrypoint), so the node must use **args launch mode** (`--args`). Consequently Vast workers connect to the hub over its **public IP** (the home server holds `192.151.156.124` directly on `ens18`, no router NAT): `docker-compose.backend.yml` now publishes API `:50555`, Redis `:6379`, S3 `:9000` and Postgres `:55432` on `0.0.0.0` (55432 avoids florist's `127.0.0.1:5432`) with matching UFW rules, while the WireGuard overlay still serves the dev host.

Validation (contract `56173069`): the node fetched its code bundle from the public API (revision `ede182f`), started the co-located ACE-Step server on the RTX 5060 Ti, consumed `oal:queue:ace-step-1.5`, and a `POST /jobs` generation reached **succeeded** with `mix_wav` pushed to hub S3 (`owners/<owner>/jobs/<job>/<attempt>/mix_wav.wav`) and served back over the public hub (200, 2,304,044 bytes, valid RIFF). The first generation is slow because the model lazy-loads on first request on the consumer card.

Known limits: exposing Redis/Postgres/S3 publicly is acceptable for validation but production should firewall the hub to worker IPs (or move the hub to a VPS) and use MinIO/managed S3; the image still carries `wireguard-tools` + the entrypoint wg bring-up for tunnel peers even though Vast uses the public IP; the dev-host worker was stopped and its env must be repointed to the new public ports if restarted. Next: operations hardening (observability, quotas, retention) or the frontend business site.


## 2026-10-16 — Multi-node autoscaling + worker cold/idle lifecycle

Author: opencode. Task type: autoscaler feature + worker lifecycle change (feature branch `impl/milestone-1`, not merged).

Reworked `scripts/autoscale.py` from a single burst node to **depth-based multi-node with tiered scale-down**: desired Vast nodes = `0` below `OAL_SCALE_UP_DEPTH` (2) else `min(ceil(depth / OAL_SCALE_JOBS_PER_NODE), OAL_SCALE_MAX_NODES)` (defaults 2 and 3), adding one node per tick; scale-down keys off how long demand has been low — hold `OAL_SCALE_TO_ONE_SECONDS` (300s), drop to one hot node, tear it down after `OAL_SCALE_DOWN_SECONDS` (1800s), reset on any spike; a node younger than `OAL_VAST_MIN_UPTIME` (180s) is never removed. State moved from a single contract to a node list (backward-compatible load). Per the owner's rule that only the worker runs on the dev server, the autoscaler now runs on the **home-server hub** (redis local; `vastai` + the Vast key installed there), not `ai-server01`.

Changed the engine worker to **own the co-located ACE-Step server**: it starts the server lazily on the first job and **stops it after `OAL_ENGINE_IDLE_STOP_SECONDS` (default 600s) idle**, so an idle baseline worker frees both GPU 0 and host RAM (the process is stopped, not merely offloaded to CPU); the first job after idle pays a cold load, jobs within the window stay warm. Ephemeral Vast nodes set the idle-stop to `0` (stay hot). The worker entrypoint no longer pre-starts acestep (unless `OAL_ENGINE_AUTOSTART=0`), and the worker image `HEALTHCHECK` now watches a worker heartbeat file (`/tmp/oal_worker_heartbeat`) instead of the ACE-Step `/health` (which is intentionally down while idle). A new `AceStepProcess` manages the subprocess in its own session so stopping reliably releases CUDA memory.

Updated: `scripts/autoscale.py`, `app/engine_worker.py`, `app/config.py`, `docker/worker-entrypoint.sh`, `Dockerfile.worker`, `docs/REMOTE_WORKERS.md`, `tests/test_engine_worker.py`. Validation: pytest **101 passed** (2 new: idle-stop stops the engine; engine-start failure requeues). A 20-job scale-out + idle-stop run against the home-server hub validates the end-to-end behavior.


## 2026-10-16 — Autoscaler: count the baseline worker + never leak a created node

Author: opencode. Task type: autoscaler correctness fix (feature branch `impl/milestone-1`, not merged).

Ran the 20-job scale-out sim against the home-server hub: depth reached ~20, the autoscaler scaled out to the cap, **all 20 jobs succeeded** with valid `mix_wav` (48 kHz stereo, ~5.7 MB), and the fleet tiered back down. Two issues surfaced. (1) Vast showed **4** instances while the autoscaler tracked 3: the first `create` returned `success: False` but still issued a `new_contract`, and `create_instance` only tracked on `success: True`, so the booted node was an untracked orphan (manually destroyed, contract `56187388`). Fixed: a create is now tracked whenever Vast returns a `new_contract`, regardless of the `success` flag. (2) `desired_nodes` ignored the always-on baseline worker, so it added Vast nodes *on top of* the dev worker (the `MAX_NODES` cap masked it at high depth). Per the owner's choice, `OAL_SCALE_MAX_NODES` now caps **total** workers: desired Vast = `max(0, min(ceil(depth / OAL_SCALE_JOBS_PER_NODE), OAL_SCALE_MAX_NODES) - OAL_SCALE_BASELINE_WORKERS)` (new `OAL_SCALE_BASELINE_WORKERS`, default 1), so at the default cap of 3 the fleet is the baseline + 2 Vast nodes.

Updated: `scripts/autoscale.py`, `docs/REMOTE_WORKERS.md`, new `tests/test_autoscale.py` (desired-nodes baseline counting + scale-down tiers). Validation: pytest **103 passed**.


## 2026-10-16 — Baseline-first tiered queues (dev worker is the entry point)

Author: opencode. Task type: queue architecture change (feature branch `impl/milestone-1`, not merged).

A 20-job sim confirmed the pipeline produces **20 distinct real `mix_wav` files** (20 distinct sha256, 0 synthetic), but the **dev baseline took only 1 job** (158 s cold load) while a warm Vast node did 18 at ~3 s each — a single shared FIFO queue (`BRPOP`) has no baseline priority, so a warm burst node out-races the cold (idle-stopped) baseline. Split the queue into two tiers so the always-on dev worker is the guaranteed entry point: `main` (baseline) and `…:burst` (Vast overflow). The dispatcher fills `main` up to `OAL_DISPATCH_BASELINE_RESERVE` (default 8) then routes to `burst`; workers pick a tier via `OAL_WORKER_TIER` (`baseline` → `BRPOP [main, burst]`, `burst` → `BRPOP [burst]` only). The autoscaler now sums both tiers for depth and uses `OAL_SCALE_JOBS_PER_NODE` default **2→8** (so ≤8 jobs run on the baseline alone; overflow drives Vast). Owner chose N=8 for max cost savings (accepts the cold-baseline tail).

Updated: `app/queue.py` (`burst_name`), `app/config.py` (`worker_tier`, `dispatcher_baseline_reserve`), `app/orchestration.py` (dispatcher routing), `app/engine_worker.py` (tiered `receive_queues`), `scripts/autoscale.py` (depth sum, N=8, `-e OAL_WORKER_TIER=burst`), `docs/REMOTE_WORKERS.md`, tests (`test_orchestration`, `test_engine_worker`, `test_autoscale`). Validation: pytest **106 passed**.
