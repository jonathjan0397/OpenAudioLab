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


## 2026-10-16 — Autoscaler tuning: N=20 (no scale-out below depth 21)

Author: opencode. Task type: policy tuning (feature branch `impl/milestone-1`, not merged).

A second 20-job run on the tiered queues showed the **warm dev baseline completing 19 of 20** jobs (Vast took 1 each) — with turbo generation (~3 s per 30 s clip) the always-on baseline absorbs a full 20-job burst on its own, so bursting to Vast at N=8 was premature. Raised the per-worker batch to **N=20** (`OAL_SCALE_JOBS_PER_NODE` and `OAL_DISPATCH_BASELINE_RESERVE` defaults 8→20): the baseline now handles up to 20 jobs alone and the fleet only scales out once total depth reaches 21. Accepted the slower first-job cold kickoff in exchange for near-zero Vast spend on typical bursts. Validation: pytest **106 passed**.

## 2026-10-16 — /lab test harness (basic-auth generate + browse page)

Author: opencode. Task type: developer tooling (feature branch `impl/milestone-1`, not merged).

Added `/lab`: a single-page test harness behind HTTP Basic (`OAL_LAB_BASIC_USER`/`OAL_LAB_BASIC_PASSWORD`, default `admin`), so generation can be exercised from a browser without minting owner tokens. `GET /lab` serves the page; `POST /lab/api/generate` admits jobs through the same durable path as the API (owner `tok_<sha256(lab-token)>`); `GET /lab/api/artifacts` browses **all** owners' artifacts; playback reuses the tokenized `/api/v1/artifacts/{id}/content`. No new storage or queue plumbing.

Updated: `app/routes/lab.py` (new), `app/config.py`, `app/main.py`, `app/routes/__init__.py`, `tests/test_lab.py` (8 tests). Validation: pytest **114 passed**; deployed as `stratastack/oal-backend:bdf89ee` on the home hub and verified end-to-end (generate → 30 s job → playable WAV).


## 2026-10-16 — Storage: drop LocalStack, durable filesystem + NFS over the WireGuard subnet

Author: opencode. Task type: storage architecture change (feature branch `impl/milestone-1`, not merged).

LocalStack persistence research settled the restart-loses-objects problem: **snapshot persistence is a licensed (Pro) feature** — Community 3.8.1 ignores `PERSISTENCE=1` (docs: Snapshots → Persistence, "Included in Plans: Base/Ultimate"; Pro image + `LOCALSTACK_AUTH_TOKEN` required). Rather than adopt the Pro image + account token, the owner chose to **drop S3 on the hub entirely**: the built-in `LocalObjectStorage` backend now roots at `/srv/oal-storage/oal` on the 1TB drive (`sdc`, ext4, UUID `f41883fc-…`, fstab `nofail`), which is NFS-exported **only to the WireGuard subnet** `10.203.0.0/24` (`rw,sync,no_subtree_check,no_root_squash`, ufw-limited to 2049/tcp from the tunnel). The dev-host worker bind-mounts the host automount (`/mnt/oal-storage`, fstab `nfs4 defaults,_netdev,nofail,x-systemd.automount`) at `/data/oal`; Vast nodes will mount in-container via the new `OAL_NFS_SOURCE` entrypoint step (`nfs-common` baked into the worker image). The bucket was empty at cutover (restart tests had already wiped it), so no migration was needed.

Durability verified: `/lab` generate → 5.76 MB WAV written by the worker over NFS onto the drive → `docker compose restart api maintenance` → artifact still listed and served (`200 audio/wav`, full byte count).

Networking hardening + Vast WireGuard: Redis `6379` and Postgres `55432` moved from `0.0.0.0` to `127.0.0.1` + `10.203.0.1` (docker-proxy bypasses ufw, so binding is the real fix); the API stays public on `50555` for `/lab`. `scripts/autoscale.py` now provisions Vast burst nodes **through the tunnel**: per-node keypair (`wg genkey`) + pooled `10.203.0.10–25` address, hub-side `wg set wg2 peer … allowed-ips` add/remove (passwordless `sudo -n wg` via `/etc/sudoers.d/oal-wg`), peer re-sync on autoscaler start, `--privileged` prepended to the Vast env string, and worker env switched to `10.203.0.1` endpoints + local storage + NFS. Caveat: earlier field notes found Vast hosts may not grant `NET_ADMIN` even with `--privileged` — first real burst node must confirm the in-container tunnel comes up (`OAL_WG_UP=1`), else fall back to public-IP transport.

Updated: `~/oal-backend/docker-compose.backend.yml` (hub; removed `object-storage`/`bucket-init`, local-storage env + bind mounts, hardened port bindings), `docker/worker-entrypoint.sh` (NFS mount step), `Dockerfile.worker` (`nfs-common`), `scripts/autoscale.py`, `docs/REMOTE_WORKERS.md`, hub `.env.backend` (`OAL_WG_HUB_PUBKEY`, `OAL_WORKER_IMAGE=stratastack/oal-worker:bdf89ee-torch2.10-cu128-wg3`). Validation: pytest **114 passed**; durability test above; autoscaler restarted on the hub with the new code; hardened `ss -tlnp` shows Redis/Postgres off the public interface.

## 2026-10-16 — Vast transport field study: public IP + ssh push-back (no tunnels on Vast)

Author: opencode. Task type: networking/storage architecture validation on Vast.ai (feature branch `impl/milestone-1`, not merged).

Goal: secure worker↔hub traffic and give Vast nodes durable storage after the S3→filesystem migration. Field results from four live burst nodes: (1) **kernel WireGuard fails** — `ip link add wg0 type wireguard` → EPERM even with `--privileged` in the CLI env string (Vast hosts deny NET_ADMIN); (2) **kernel NFS mount fails** — `mount.nfs4: failed to prepare mount: Operation not permitted` (no CAP_SYS_ADMIN); (3) **Tailscale userspace mode joins the tailnet fine** (hub `strata-stack-primary` 100.76.27.39, workers ephemeral-ish via reusable auth key) **but cannot route raw app TCP** — without NET_ADMIN the 100.64/10 route never lands in the container netns, so `tailscale ping` works while curl/redis/psycopg SYNs blackhole (0 packets on the hub's `tailscale0`). Decision (owner-approved): Vast workers use the **hub's public IP** for API/Redis/Postgres/ssh; Redis got `requirepass` (`OAL_REDIS_PASSWORD`) since it is now public; storage durability on Vast = **rsync push-back** (entrypoint sidecar mirrors container-local `/data/oal/` to `administrator@hub:/srv/oal-storage/oal/` every 2 s with a dedicated deploy key). The dev-host baseline keeps the WireGuard overlay + host-side NFS mount. The autoscaler became a **systemd service** (`oal-autoscale.service`) after ad-hoc nohup runs kept dying with ssh sessions, and gained a **burst-drain guard**: never destroy a node while the burst queue still has work (a node was previously killed mid-generation). Also fixed: `vastai destroy` can take ~45 s (looked like a stuck loop), and auth keys are single-use unless "reusable" is checked.

Status: hub + baseline fully migrated and durability-verified; Vast compute path verified (node generated 20 burst jobs end-to-end over public IP); push-back delivery needs one more observed node run (the last node's outputs were lost when it was destroyed pre-guard), and the autoscaler's `OAL_VAST_TRANSPORT` defaults to `public`.

Updated: `docker/worker-entrypoint.sh` (Tailscale + push-back sidecar), `Dockerfile.worker` (tailscale static binaries, openssh-client, rsync, nfs-common), `scripts/autoscale.py` (transport selection, push env, burst-drain guard, systemd), `~/oal-backend/docker-compose.backend.yml` (Redis requirepass, public binds restored), hub `.env.backend` (`OAL_REDIS_PASSWORD`, `OAL_TS_*`, `OAL_PUSH_PRIVKEY_B64`), new `oal-autoscale.service`, `docs/REMOTE_WORKERS.md`. Validation: pytest **114 passed**; live burst node produced 20 artifacts via public IP.

## 2026-10-19 — Guest access, Beginner subscription, signup policy, and billing periods

Author: opencode. Task type: feature implementation (branch `impl/guest-beginner-billing`, not merged).

Implemented server-issued guest sessions with cookie identity, UTC daily guest song quota, two-minute guest duration cap, reservation commit/release on terminal job transitions, and guest song claim into a signed-in account. Removed arbitrary bearer fallback: registered API keys, account cookies, and guest cookies are the supported public identities. Added policy documents/acceptances, email verification/password reset tokens, SMTP-backed transactional email with pending fallback, admin guest/policy/abuse/audit read surfaces, public pricing, Beginner `$5/month` for `1,000` credits, visible pricing rows, subscription period state, Stripe checkout price-id support, and webhook handling for checkout completion, subscription updates/cancellation, and `invoice.paid` renewals.

Updated backend config/models/migration `0025`, auth/jobs/billing/admin routes, orchestration terminal transitions, frontend API types, guest allowance/policy UI, signup confirmation, public pricing, policy/verify/recover routes, and admin Guests/Policies panels. Validation: backend pytest **202 passed**; frontend `npm run build` passed. Stripe package was installed into the local `.venv` because the webhook test imports it.

## 2026-10-19 — Baseline worker recovery, Qwen3 fallback LLM, and autoscaler fallback

Author: opencode. Task type: implementation + live deployment validation (branch `impl/milestone-1`, not merged).

Recovered the dev-host baseline worker with stable ids (`oal-baseline-gpu0`, `oal-baseline-gpu0-audio`) and added worker health state (`last_error`, `unhealthy_until`, Alembic `0026`) so OOM/engine-start failures can temporarily mark a worker unhealthy. Extended the autoscaler to health-check the baseline worker and create a low-cost North-American fallback node after 5 minutes of baseline unavailability. The fallback runs `engine_worker,audio_worker` as `OAL_WORKER_TIER=baseline`, consumes the main queue, and is destroyed 5 minutes after baseline restoration.

Baked the standard OAL LLM into the worker image: Qwen3-4B Q4_K_M GGUF served by `llama.cpp` on port 8082 with `--reasoning-budget 512`. Added dynamic LLM endpoint selection through `site_settings.llm_base_url`, with `/llm/draft` and lyrics-write using hybrid thinking and humanize/style/title using non-thinking mode. The autoscaler maps the fallback LLM port through Vast, writes the public endpoint to the backend, and restores `OAL_PRIMARY_LLM_BASE_URL` after baseline recovery.

Updated: `app/config.py`, `app/models.py`, `alembic/versions/0026_worker_health.py`, `app/engine_worker.py`, `app/engine_acestep.py`, `app/audio_worker.py`, `app/training_worker.py`, `app/llm.py`, `app/routes/llm.py`, `app/routes/internal.py`, `scripts/autoscale.py`, `scripts/run_house_workers.sh`, `Dockerfile.worker`, `docker/worker-entrypoint.sh`, tests, `docs/REMOTE_WORKERS.md`, and `CHANGELOG.md`. Deployed backend image `stratastack/oal-backend:baseline-fallback` and worker image `stratastack/oal-worker:45e39a5-torch2.10-cu128-ts8-qwen3`.

Validation: backend pytest **203 passed**. Live fallback test stopped the baseline worker, created Vast contract `56795630` (Tesla V100, Utah, `$0.148/hr`), switched the LLM endpoint to `http://67.182.226.160:20680/v1`, completed `/llm/title`, `/llm/draft`, `/llm/lyrics`, `/llm/style-prompt`, and generation job `e2b1d3fc-7a55-4268-80ae-5f10e9939ceb`. Restarting the baseline worker restored `http://10.203.0.2:8082/v1` and destroyed the fallback after the restore grace.

## 2026-10-20 — House LoRA merge A/B and corrected multi-LoRA merge semantics

Author: opencode. Task type: model merge experiment + live Vast validation (branch `impl/milestone-1`, not merged).

Goal: fold the 13 trained house genre LoRAs into ACE-Step Turbo checkpoints and A/B the merged variants against baseline Turbo. The first full run used PEFT `add_weighted_adapter(..., combination_type="linear")` with raw per-adapter weights `[0.30] * 13`, `[0.50] * 13`, and `[0.70] * 13`. The merged audio was unrecognizable as music.

Research: ACE-Step runtime LoRA strength is a 0–1 multiplier applied to the active PEFT adapter via `set_lora_scale` / `apply_scale_to_adapter`. ACE-Step’s own `merge_lora_weights` simply calls `merge_and_unload()` for the active adapter; it does not define a multi-LoRA merge procedure. PEFT `linear` task arithmetic sums adapter matrices with the supplied weights, so 13 adapters at raw `0.30` produced roughly `3.9x` total LoRA strength. That explained the corrupted first A/B.

Corrected method: use PEFT `combination_type="cat"` and normalize weights by the number of adapters. With 13 adapters, scale `0.30` now means total merge strength `0.30`, with each genre contributing `0.30 / 13`. `cat` preserves the weighted sum of LoRA deltas more directly than `linear`, which sums A and B separately and can introduce cross terms.

Validation runs:
- One-adapter sanity: `house-v1-pop` only, scale `0.30`, `combination_type=cat`, Vast contract `56826462`, remote `/srv/oal-storage/house-lora/merge-ab-one2-2026-10-19`, local `/Cold-Archive/OpenAudioLab/house-lora-ab/2026-10-19-one-pop/`.
- Corrected full A/B: all 13 house LoRAs, scales `0.30,0.50,0.70`, `combination_type=cat`, Vast contract `56827635`, remote `/srv/oal-storage/house-lora/merge-ab-v2-2026-10-19`, local `/Cold-Archive/OpenAudioLab/house-lora-ab/2026-10-19-v2/`.

Updated: `scripts/house_merge_ab.py`, `scripts/house_merge_ab_agent.sh`, `Dockerfile.house_merge`, `curation/house_ab_prompts.json`, `curation/house_ab_prompts_test.json`, `CHANGELOG.md`, and `docs/HOUSE_LORA_TRAINING.md`. Built/pushed `stratastack/acestep-train:v3-house-ab`, `v4-house-ab`, and `v5-house-ab`. The final agent defers checkpoint push until after audio/metadata because node-to-hub upload can be slow.

`docs/HOUSE_LORA_TRAINING.md` now fully documents the end-to-end process: curation, tensor preprocessing, Vast training-agent flow, actual house-v1 hyperparameters and final checkpoint losses, ACE-Step LoRA runtime semantics, the failed first merge, the corrected `cat` + normalized-weight merge, sanity/full A/B runs, retention paths, promotion plan, and known pitfalls.

Retention: all 13 trained LoRAs remain on the hub under `/srv/oal-storage/house-lora/house-v1-*/adapter`; corrected merged checkpoints are retained locally under `/Cold-Archive/OpenAudioLab/house-lora-ab/2026-10-19-v2/merged/` and on the hub under `/srv/oal-storage/house-lora/merge-ab-v2-2026-10-19/merged/`.

## 2026-10-20 (later) — Promoted house_070 to the production default

Owner chose `house_070` (corrected `cat`-normalized merge, total scale `0.70`)
as the winner and asked to promote it immediately.

Deployment shape: the combined worker image does **not** bake
`/opt/acestep/checkpoints`; every node (baseline + Vast burst) materializes the
base DiT/LM/VAE/embedding from the HuggingFace cache volume on first init. The
house checkpoint has no HF-repo entry, so it must be baked. Built
`Dockerfile.house_worker` as a thin layer over
`stratastack/oal-worker:45e39a5-torch2.10-cu128-ts8-qwen3` that COPYs the house
checkpoint in as `acestep-v15-house-turbo` (stable name; original
`acestep-v15-turbo` still materializes for rollback). Pushed
`stratastack/oal-worker:house-v1-070`.

Config: `scripts/run_house_workers.sh` IMAGE + baseline
`ACESTEP_CONFIG_PATH/OAL_ACESTEP_MODEL=acestep-v15-house-turbo` (gpu1 training
worker intentionally left on the base DiT); `scripts/autoscale.py` gained
`OAL_ACESTEP_MODEL` (applied to generation roles only); hub `.env.backend` set to
the new image tag + model; `oal-autoscale.service` restarted (picks up env on
future burst/fallback nodes).

Validation: baseline recreated on the House image, health=healthy; in-container
`/v1/init` returned `loaded_model: acestep-v15-house-turbo` and auto-restored
`acestep-v15-turbo`, `acestep-5Hz-lm-1.7B`, `vae`, `Qwen3-Embedding-0.6B`; a real
10 s instrumental `release_task` produced valid PCM WAV (48 kHz, stereo). Backend
pytest still 203 passed. `.gitignore` excludes the 28GB `house-lora-ab/` review
folder.

## 2026-10-20 — Generation contract repair + ACE-Step control parity audit (branch `feat/generation-contract`)

Author: opencode. Task type: spec milestone 0–2 (contract/identity) + control-parity audit.

Ground truth first. Rechecked remotes/branches/PR instead of assuming: `master` (b878d71)
already contains the `impl/guest-beginner-billing` snapshot `9d70eaf` plus newer house-promotion
work, and the CONTROL_UNSUPPORTED bug was still present on it (`CreateWidget.tsx` set
`controls.description` / `controls.styles`). PR #1 (`origin/fix/generation-controls` @ `1332528e`)
removes exactly those two lines and was not merged. Chose to branch from `master` (strict
superset; preserves newest work) and apply the equivalent correction + the surrounding contract
repair rather than cherry-pick a stale-log commit.

Root-cause beyond the two-line fix: the pinned worker source (`/opt/acestep` @ `ca1e85f`,
`release_task_models.GenerateMusicRequest`) shows the adapter forwards only
`bpm,key_scale,vocal_language,inference_steps,guidance_scale,shift,variations,seed,audio_duration,
model,prompt,lyrics`. `mood` is consumed solely by `_auto_lora_match`; `gender` is consumed by
nothing; `shift` is documented base-only (a no-op on the deployed Turbo model) yet the UI called it
"Weirdness"; the widget hardcoded `lyrics_origin="frontend_llm"`, pre-seeded the live idea with a
random example, and `.trim()`ed approved lyrics.

Changes:
- `frontend/src/lib/generation.ts`: single canonical serializer for every theme + Studio; emits
  `song_idea` + `style_prompt` + resolved `music_description` caption (idea, mood, singer, style
  folded in so the preference is actually effective), preserves exact lyrics, uses real
  provenance (`human` vs `frontend_llm`), and only emits registry-supported controls.
- `app/schemas.py`: added `song_idea`/`style_prompt` to `GenerateJobRequest`; auto-persisted in
  `request_json` (recipe) — no hidden free-text in the control bag.
- `app/registry.py`: unchanged (mood/gender remain accepted to preserve the tested API contract);
  parity doc records their real consumption.
- `frontend/src/api.ts`: typed `ApiError` envelope exposing `unknown_controls`/`supported_controls`
  + `request_id` and an actionable `controlHint()`; strict backend rejection untouched.
- `frontend/src/components/CreateWidget.tsx` + `Studio.tsx`: use the serializer; empty idea default
  with click-to-accept example chips; shift slider relabeled "Timestep Shift", disabled with a
  Turbo no-op note; Studio hydration reads the independent metadata with legacy fallback.

Verification: backend `pytest 206 passed` (added `tests/test_generation_contract.py`:
description/styles still rejected with field details + no job/idempotency record created;
corrected payload with independent metadata admitted and persisted). Frontend `tsc -b && vite
build` clean. Serializer executed directly against the real code for idea-only/style-only/both/
instrumental/shift-0/auto-lyrics cases.

Honest scope: this lands milestones 0–2 (contract) + the parity audit. Real source-conditioned
remix/vocal/melody/repaint and extract/lego/complete (3A), the full advanced-control transport
bridge (3B), and their real-audio gates (3C) remain not-wired / engine-blocked (Turbo worker, no
`src_audio_path`/`task_type`/repaint bridge). Branch committed to `origin/feat/generation-contract`;
not merged, not deployed (per spec).

## 2026-10-20 — Deployed the generation-contract fix to production (master)

Merged `feat/generation-contract` (fast-forward) into `master` and deployed.
Cleanup: pruned merged local `impl/*` branches; left remotes and the superseded
PR #1 branch as-is. Added `house-lora-ab/` and other large local trees to
`.dockerignore` (the image build context had them).

Deploy: built+pushed `stratastack/oal-backend:gen-contract-9be4753` (the root
`Dockerfile` builds the frontend into the backend image, so one image ships the
API + SPA) and set hub `OAL_IMAGE_TAG=gen-contract-9be4753`; `compose up -d`
recreated api/dispatcher/maintenance (alembic upgrade head = no-op). No worker
image change (contract fix is API+frontend only). Added `song_idea`/`style_prompt`
to the durable generation manifest (`orchestration._generation_manifest`) with a
test, so the Creation Card and Studio recreation capture them.

Live verification on the baseline worker/house-turbo:
- legacy `controls.description`/`styles` -> HTTP 422 CONTROL_UNSUPPORTED with
  `unknown_controls`/`supported_controls` (strict rejection intact);
- corrected payload (`song_idea`/`style_prompt` + caption + `controls.bpm`) ->
  202 -> succeeded -> real 5.76 MB 48kHz stereo WAV; manifest.requested now shows
  `song_idea`/`style_prompt` and no free-text in controls.

Operational gotcha recorded: the engine worker builds the manifest from the app
**code bundle it fetches from the backend at container startup** (not baked into
the worker image). After a backend deploy that changes `app/`, the running worker
holds the STALE bundle until restarted — which initially left `song_idea`/
`style_prompt` absent from the card. Fix: `docker restart oal-worker-hub` to
re-pull the bundle (worker image itself unchanged).

## 2026-10-20 — Roadmap Phase 1: capability registry + control validation (branch `feat/phase1-capability-registry`)

Author: opencode. Task type: roadmap execution (Phase 1 of the approved plan).

Made `app/registry.py` the single capability source: `ControlSpec` (type, range/length,
default, label, unit, model-family applicability) + per-release `supported_task_types`
(`text2music/cover/cover-nofsq/repaint` for Turbo) and `model_family`. `CONTROL_SPECS` is
derived into `control_capabilities(model_id)` and `validate_controls(model_id, controls)`.

Behavior changes (keeps strict rejection, adds value + applicability checks):
- `jobs.py` now raises `CONTROL_INVALID` with per-field details for out-of-range/wrong-type
  values (e.g. `bpm:999`, `bpm:"fast"`), and returns no reservation on rejection.
- Base-only `shift` is excluded from the Turbo `supported_controls`, so it is rejected as
  `CONTROL_UNSUPPORTED` instead of accepted-but-ineffective (fixes the "appears effective"
  defect at the API boundary).
- `time_signature` added end-to-end: registry + `GenerateJobRequest` (already via controls),
  forwarded by `engine_acestep.build_payload`, captured in `_generation_manifest` requested,
  surfaced in Studio recreation.
- `GET /models/{id}` returns `controls` metadata + `supported_task_types` + `model_family`.

Frontend: `generation.ts` is now capability-driven — accepts a `supportedControls` override,
filters candidate controls to it (so a base-only `shift` never ships for Turbo, but a
`shift:0` from a base-capable model is preserved), adds `timeSignature`. `CreateWidget` fetches
model capabilities and passes them; Advanced mode exposes a "Time sig" field; Studio hydrates it.

Verification: backend `pytest 212 passed` (6 new: range/type/shift-on-turbo/time_signature/
adapter-forward/model-detail). Added a real test runner (`vitest`) — `frontend/src/lib/
generation.test.ts` 9 tests pass (idea/style out of controls, singer-folding, exact-lyrics
provenance, instrumental lyric omission, capability filtering, numeric controls, shift:0,
caption fallback, seed omission). `tsc -b && vite build` clean.

Scope: Phase 1 only; not merged to `master`, not deployed. Next per plan: Phase 2 (Turbo-native
cover/remix/repaint with the `_stage_asset` private-path pattern + real-audio acceptance on the
baseline GPU).

## 2026-10-20 — Roadmap Phase 2: source-conditioned cover/repaint (backend) (branch `feat/phase2-source-conditioned`)

Stacked on the Phase 1 branch (not deployed; Phase 1 kept on branch per owner).

Schema (`app/schemas.py`): typed `task_type`, `src_asset_id`, `reference_asset_id`,
`audio_cover_strength`, `cover_noise_strength`, `repainting_start/end`, `repaint_mode`,
`repaint_strength`, `chunk_mask_mode`.

Admission (`app/routes/jobs.py`): `_validate_source_task` checks task support vs the model
release, requires an owned source for cover/cover-nofsq/repaint, verifies each referenced
asset is owned + audio (re-checks on cross-owner/deleted), and enforces region bounds. Strict
rejections: TASK_UNSUPPORTED / SOURCE_REQUIRED / SOURCE_NOT_FOUND / SOURCE_INVALID /
SOURCE_REGION_INVALID, all before any reservation.

Worker (`app/engine_worker.py`): `_payload_for` -> `_source_for` builds the upstream source map
(returns None for plain text2music so the payload is unchanged) and `_stage_asset` resolves an
owned asset to a content-hashed local path via object storage, re-checking ownership.
`engine_acestep.build_payload` forwards the mapped fields. `orchestration._generation_manifest`
records task/source/region lineage.

Key engine finding (verified against the deployed worker at ca1e85f): `release_task_audio_paths.
validate_audio_path` rejects absolute paths outside the system temp dir and any `..`. So the first
cover attempt with `/opt/acestep/asset-stage/src.wav` failed with "absolute audio file paths are
not allowed"; staging under `/tmp` (config default now `OAL_ASSET_STAGE_DIR=/tmp/oal-asset-stage`)
succeeded. A real `task_type=cover` + temp-staged `src_audio_path` produced a real 15 s source-honored
WAV from the deployed Turbo/house model — confirming the model+engine path, not just our glue.

Verification: backend `pytest 221 passed` (new tests/test_source_conditioned.py: adapter mapping,
plain text2music passthrough, TASK_UNSUPPORTED/SOURCE_REQUIRED/SOURCE_NOT_FOUND, owned-source
admission + manifest lineage, temp staging writes content-hashed file, cross-owner deny).

Next (Phase 2 UI): Studio "Remix/Repaint" source picker + region selection + A/B; then repaint/
extension real-audio gates. Not merged/deployed.

Phase 2 UI (same branch): added a Studio per-track "✦ Remix" action that builds a real
`task_type=cover` request via the canonical serializer (target style + the take's owned
`src_asset_id`, instrumental, clamped duration) and POSTs it, with inline pending/error/queued
feedback. `generation.ts` gained optional `taskType`/`srcAssetId`/`referenceAssetId`/
`audioCoverStrength`/`coverNoiseStrength` emitted as top-level fields (never control-bag).
Serializer `vitest` extended to 11 (cover mapping + text2music passthrough). Frontend build clean;
backend unchanged at 221. Still on `feat/phase2-source-conditioned`, not deployed; full
OpenAudioLab-path live cover E2E + repaint/extension real-audio gates require a deploy.

## 2026-10-20 — Deployed Phase 1+2 (capability registry + source-conditioned cover/repaint) and ran live gates

Merged stacked branch to `master` (FF) -> `32b855d`; built+pushed
`stratastack/oal-backend:gen-contract-32b855d` (frontend+API in one image); hub
`OAL_IMAGE_TAG=gen-contract-32b855d`; compose up (migrate no-op); **restarted
`oal-worker-hub`** to pull the new code bundle (its `/srv/openaudiolab/code` now
contains `_stage_asset`/`task_type`).

Live OpenAudioLab-path real-audio gates on the baseline worker (house-turbo), via the
guest API (authorized baseline GPU):
- source take -> succeeded (2.88 MB, 48kHz stereo, 15s, non-synthetic);
- COVER `task_type=cover` + `src_asset_id` + `audio_cover_strength=0.6` -> succeeded,
  real audio; manifest lineage task_type=cover, src set;
- REPAINT `task_type=repaint` + `src_asset_id` + region 2.0-8.0 + repaint_mode/strength
  -> succeeded, real audio; lineage region captured.
Negative gates (no reservation/charge; guest counter unchanged at 3):
- extract -> 422 TASK_UNSUPPORTED (lists Turbo task types);
- cover w/o src -> 422 SOURCE_REQUIRED;
- cover w/ unknown src -> 404 SOURCE_NOT_FOUND;
- controls.shift on Turbo -> 422 CONTROL_UNSUPPORTED (Phase 1 strictness intact).

Rollback: set OAL_IMAGE_TAG to the prior tag and compose up -d (+ restart worker).
extract/lego/complete remain base-family-only (out of scope for the Turbo worker).
Phase 2 UI (cont.): Studio "✦ Repaint" region picker. `generation.ts` gained
`repaintingStart/End`, `repaintMode`, `repaintStrength`, `chunkMaskMode` (top-level
typed fields, only when present; text2music unchanged; `repainting_start:0` preserved).
The repaint mutation posts a real `task_type=repaint` job with the owned `src_asset_id`
and the entered seconds-region. Serializer vitest -> 13. Live OpenAudioLab-path repaint
with the exact payload succeeded: 15s 48kHz stereo real audio, lineage region 3–11 /
balanced / 0.6 / chunk auto. Honest limits surfaced: genuine lengthening/continuation
is a distinct capability (repaint only edits within the clip), not faked.

## 2026-10-20 — Phase 3 (multi-model) backend: catalog, entitlements, quotes, Turbo CFG lock, capability routing (branch `feat/phase3-multimodel`)

Implemented the multi-model platform core (Stages A–D + lineage), tested, no
premature exposure of unrun models.

- `app/catalog.py`: versioned catalog of the four public `model_selections` ->
  engine releases + execution profiles + a provisional `PRICE_POLICY_VERSION`
  (turbo 1.0, sft 2.0, xl 4.0, merge 1.5; compute_factor default 1.0). Only
  `turbo-fast-v1` is `available`; `sft-quality-v1` is available-but-gated by a
  registered `worker_capability`; `xl-sft-premium-4b-v1` and
  `merge-experimental-v1` are `unconfigured` -> 503 (never a silent Turbo
  downgrade). Engine-grounded: Turbo locks steps=8/CFG=1.0; SFT/XL 50–100 /
  CFG 2–3 / DCW off; `sampler_mode`/ancestral/600-step rejected (not native to
  ca1e85f); effective-NFE ceiling derived from `timesteps`.
- `app/entitlements.py`: premium requires a real paid subscription resolved from
  the account behind a cookie OR an account API key (`usr_` owner). A balance or
  plan label is not entitlement; guests/unsubscribed -> 403; Turbo unaffected.
- Migrations 0027 (`quotes`), 0028 (`worker_capabilities`, `gpu_leases`).
- `routes/jobs.py`: `model_id` now optional; `POST /api/v1/generation/quote`
  issues owner+hash-bound quotes with a TTL; `create_job` resolves the catalog,
  enforces entitlement + eligible worker + profile controls, binds and consumes
  the quote, and charges exactly the quoted amount atomically (403/402/409/503/422
  per spec). Turbo charge and guest 4/120s limits unchanged.
- `orchestration`: Creation Card records model_selection/profile/engine/planner/
  family + quote_id/policy_version/reserved_credits.
- `GET /api/v1/model-selections` returns public catalog (ranges/availability/
  pricing, no engine paths); OpenAPI exposes the new endpoints.

Tests: backend **232 passed** (new `tests/test_multimodel.py`: Turbo lock,
entitlement 403, unconfigured 503, no-compatible-worker 503, QUOTE_REQUIRED,
quote bind + 2x charge, tamper, expiry, catalog shape, OpenAPI). Frontend build
+ vitest unchanged (13).

**Remaining this phase (NOT done, NOT faked):** Stage E GPU-0 alternation runtime
(worker model-swap under a fenced lease + VRAM re-check + planner in-process),
Stage F provisioning `acestep-v15-sft` + live SFT audio validation, Stage G UI
model selector + per-model drafts + quote display. Premium is honestly gated until
a validated worker runs it. Nothing merged/deployed yet this phase.

## 2026-10-20 — Phase 3 framework DEPLOYED (catalog/entitlements/quotes/capability routing/UI) + live-verified

Merged `feat/phase3-multimodel` -> `master` (`bfb0f87`, FF). Built+pushed
`stratastack/oal-backend:mm-bfb0f87`; hub `OAL_IMAGE_TAG=mm-bfb0f87`; compose up
applied migrations 0027 (quotes) + 0028 (worker_capabilities, gpu_leases);
restarted `oal-worker-hub` to pull the new bundle.

Live verification on the deployed stack:
- guest TURBO generation -> succeeded, real 2.88 MB/48kHz/15s non-synthetic audio;
  Creation Card records `model_selection=ace-step-1.5-turbo` and reserved 10
  credits (unchanged base) -> the serialized routing path did not regress Turbo.
- guest premium `ace-step-1.5-sft` -> 403 (premium requires paid subscription).
- `ace-step-1.5-xl-sft` -> 503 MODEL_UNAVAILABLE (unconfigured).
- `GET /model-selections`: turbo `runnable=True`; sft/xl/merge `runnable=False`.
- `worker_capabilities` auto-registered by the worker: turbo enabled, sft
  `enabled=f` (checkpoint not installed). Premium is honestly gated and never
  silently downgraded to Turbo.

Still remaining for full Phase 3 (NOT done, NOT faked): Stage F provision
`acestep-v15-sft` into a worker + run the first REAL SFT audio through the
serialized GPU-0 swap and validate it; measured compute factors / peak-VRAM
benchmarks; community merge validation. SFT stays capability-gated (503) until its
checkpoint is provisioned + validated.

## 2026-10-20 — Phase 3 SFT live-attempt surfaced a real bug -> durable premium guard deployed (master 5dbf47a)

Provisioned `acestep-v15-sft` (4.79 GB) onto the baseline worker and ran a real
SFT job through the deployed path. Result was NOT a validated SFT: the job
completed with real audio but `engine_version` reported `acestep-v15-house-turbo`
-- the baseline runs an *externally-started* ACE-Step server
(`OAL_ENGINE_AUTOSTART=0` -> `engine_process is None`), so my in-worker model
swap never applied, and the server's on-demand model switch is not (yet) proven
to honor the request. A paid premium request was effectively served by the wrong
model. I did NOT ship that.

Fixes:
- Rolled back the throwaway paid account (deleted its user/api_key/credit_entry/
  job/quote rows and its sft capability) so no mis-charge persists.
- Durable guard (redeployed): a non-turbo `execution_profile` is advertised as a
  worker capability ONLY when its id is in `OAL_PREMIUM_PROFILES_ENABLED` AND the
  checkpoint is installed. Checkpoint presence alone no longer enables premium.

Re-deployed `stratastack/oal-backend:mm-5dbf47a` + restarted worker. Live after
the fix: `model-selections` -> turbo runnable=True, sft/xl/merge runnable=False
(even with the sft checkpoint present) -> premium 503s instead of being served by
Turbo; a real guest Turbo generation still succeeds (no regression). Backend 236
passed, vitest 15, build clean.

**Remaining (genuinely not done, gated by the allowlist):** validate the
server-side on-demand model routing so a premium job actually loads
`acestep-v15-sft` within GPU-0 VRAM budget (or run a dedicated premium worker),
confirm `engine_version`/audio reflect SFT, then set `OAL_PREMIUM_PROFILES_ENABLED
=sft-quality-v1`. Until then premium is honestly unavailable (503), never faked.

## 2026-10-20 — SFT genuinely validated on GPU-0 (worker-managed serialized swap)

Root cause of the earlier mis-serve: the baseline ran `OAL_ENGINE_AUTOSTART=0`, so
the ENTRYPOINT started an external, model-pinned (house-turbo) server and the
worker's `engine_process` was `None` -> my swap never applied. And `ensure_running`
only swapped when its tracked `self.model` was already known, so the first premium
job after a warm/unknown start just relabeled.

Fixes deployed (master `2e7fedd`, backend `mm-2e7fedd`):
- Baseline worker now runs `OAL_ENGINE_AUTOSTART=1` (worker-managed lazy engine:
  entrypoint no longer pins an external server) + `OAL_PREMIUM_PROFILES_ENABLED=
  sft-quality-v1` + a persisted `acestep-v15-sft` bind-mount (copied to
  `/Cold-Archive/oal-models/` so it survives container recreation).
- `AceStepProcess.model` defaults to the env checkpoint and `ensure_running` stops
  + reloads whenever the requested model differs.

Live proof (real audio, via the API/worker on GPU 0):
- SFT job -> `engine_version = ace-step-1.5/acestep-v15-sft`, 2.30 MB non-synthetic
  48 kHz stereo 12 s, reserved 20 credits (base 10 x 2.0 multiplier).
- Follow-up Turbo job -> swapped back, `engine_version = .../acestep-v15-house-turbo`.
- Serialized alternation confirmed both directions on the single GPU 0.

Benchmark note: peak GPU-0 memory during a 12 s / 50-step SFT job was ~16.2 GB
(turbo baseline incl. llama-server ~16.9 GB) -- fits the 24 GB card with headroom.
`compute_factor` remains provisional 1.0 pending a broader duration/batch sweep;
the 2.0x multiplier is a proposed starting value, not a measured tariff.
`xl-sft-premium-4b-v1` (4B planner ~12 GB) and the community `merge-experimental-v1`
remain `unconfigured` (503) -- the pinned engine has no `acestep-v15-xl-sft` repo id
and the merge lacks an approved checkpoint/license/VRAM profile. Throwaway paid
test accounts were removed (0 left).

## 2026-10-20 — Entitlement fix: paid TIER (plan) grants premium; higher tiers validated

Reported bug: Pro/Premier accounts got "This model requires an active paid
subscription (Beginner or higher)" when selecting premium models. Diagnosis on the
live DB: there were 11 `pro` users with `subscription_status` NULL (plan set, but no
Stripe subscription row), and the old `has_paid_subscription` *required*
`subscription_status in {active,trialing,canceling}`, so those (and any similarly
provisioned higher-tier account) were denied.

Fix (`app/entitlements.py`, master 7ba57cd, deployed as `oal-backend:ent-7ba57cd`):
the server-set `plan` is the authoritative tier; `subscription_status`/
`current_period_end` only *revoke* entitlement when the state is terminal
(canceled/unpaid/incomplete/expired/paused) or the billing period has lapsed. A paid
tier with a NULL status is now entitled; free/expired/cancelled are not.

Validated: unit matrix (beginner/pro/premier across active/null/canceling/expired/
canceled/free/disabled); API `tests/test_multimodel.py` (pro/premier run SFT 202;
premier on un-provisioned xl/merge -> 503 availability, not 403; free/guest premium
-> 403). LIVE: a fresh `pro` account with NULL subscription_status quoted (200) and
ran a real SFT job to success (`engine_version=acestep-v15-sft`, reserved 20).
Throwaway accounts removed. Backend 243 passed.

Premium/experimental provisioning status (honest, not faked):
- `ace-step-1.5-sft` -> installed + live-validated for all paid tiers.
- `ace-step-1.5-xl-sft` -> the pinned ca1e85f engine has NO `acestep-v15-xl-sft`
  mapping; ACE-Step publishes only an `acestep-v15-xl-sft-diffusers` (different
  format/runtime) and XL+4B-planner exceeds this single 24GB GPU-0 alongside the
  always-on services -> remains `unconfigured` (503). Enabling needs a dedicated
  higher-VRAM worker or a validated diffusers runtime path (separate effort).
- `ace-step-1.5-merge-sft-turbo` -> no approved community checkpoint/license/VRAM
  profile exists -> remains `unconfigured` (503), never advertised.
The allowlist (`OAL_PREMIUM_PROFILES_ENABLED`) means enabling either later is a
config + validated-checkpoint action, with entitlement already correct for every
paid tier.

## 2026-10-20 — Admin premium fixed; XL + community-merge made operator-enableable (not auto-on)

- Admins are now entitled to premium models (role=='admin' bypass) -- verified live:
  admin SFT quote 200; admin XL/merge correctly 503 (nothing provisioned). Live API
  on `oal-backend:adm-df487d4`. Test admin key removed.
- XL and experimental are no longer hardcoded off. They turn on only when an operator
  sets `OAL_XL_CHECKPOINT_ID` / `OAL_MERGE_CHECKPOINT_ID` to a VALIDATED native
  checkpoint, installs it, and allowlists the profile -- reusing the same proven
  allowlist + serialized-swap + quote/quota path that carries SFT.

Why XL-SFT and the merge are NOT switched on in this environment (evidence, not excuses):
- Native XL (`ACE-Step/acestep-v15-xl-turbo`, `-xl-base`) model.safetensors ~20 GB, MIT.
  The 24 GB GPU 0 also permanently hosts llama-server (~4 GB); with the always-on Turbo
  swapped out there is ~20 GB -- XL weights + VAE/text-encoder/planner/activations exceed
  it. The pinned ca1e85f runtime has NO `device_map`/`enable_model_cpu_offload`/
  `use_tiled_decode` (grep: none) so there is no CPU-offload path to shrink the footprint.
- Native `acestep-v15-xl-sft` is not published (only `acestep-v15-xl-sft-diffusers`,
  a different Diffusers format the native ACE-Step handler does not load).
- No community "merge" checkpoint is approved: ACE-Step ships none, and the spec forbids
  silently choosing a third-party repo without an exact repo/revision/hashes/license/
  VRAM/runtime validation.
Enabling XL needs either a dedicated >=32-48 GB worker (new authorized paid infra) or an
offload-capable runtime change (violates version pinning). Enabling the merge needs a
specific operator-approved checkpoint + license check.

## 2026-10-20 — VRAM-gated premium registration (deployed, vram-5ea06c7)

Premium profiles are advertised only when allowlisted AND installed AND this
worker's measured total VRAM >= the profile floor (turbo 14G / sft 15G / merge 16G /
xl-sft 32G). On the shared 24 GB GPU 0 this keeps SFT available and NEVER advertises
XL-SFT (which cannot fit), so a premium job can't be dispatched/charged onto a worker
that would OOM. Live re-verified: turbo+sft runnable, xl+merge un-advertised 503,
and a real SFT render still succeeds on acestep-v15-sft.

XL offload conclusion (why not "implemented in runtime" here): the pinned ca1e85f
loader uses per-tensor `.to(device=...)` with no device_map/accelerate hook, XL is
~20 GB of weights, and GPU 0 also hosts llama-server -- there is no offload path and
insufficient VRAM, so a correct XL run needs a dedicated >=32/48 GB worker (config +
allowlist now lights it up automatically), not a runtime fork on this node.

## 2026-10-20 — XL (4B DiT) corrected + provisioned on the 24 GB baseline worker

Deep-research pass **corrects** the two "XL cannot run here" conclusions recorded
above (lines ~604-655). Those conclusions were based on three false premises that
are now refuted against the pinned `ca1e85f` runtime + the live Hugging Face repos:

1. **XL is a first-class native model in the pinned runtime**, not diffusers-only.
   `ACE-Step/acestep-v15-xl-sft` and `ACE-Step/acestep-v15-xl-turbo` are published
   native HF repos (4x fp32 safetensors shards + `modeling_acestep_v15_xl_base.py`
   / `modeling_acestep_v15_xl_turbo.py` custom code, `model_type=acestep`, MIT). The
   loader (`init_service_loader.py`) calls `AutoModel.from_pretrained(..., dtype=self.dtype)`,
   converting the ~19.9 GB fp32 shards to **~9 GB bf16** resident -- matching upstream
   `gpu_config.py` `MODEL_VRAM["dit_xl_base"]=9.0`.
2. **The pinned runtime already has offload + tiling** (contrary to the grep above):
   `offload_to_cpu` / `offload_dit_to_cpu`, torchao `int8_weight_only`/`fp8_weight_only`/
   `w8a8_dynamic`, `use_tiled_decode` (default True at REST), `MAX_CUDA_VRAM` debug, and an
   XL-aware `_vram_guard_reduce_batch`. No runtime fork is required.
3. **24 GB is the upstream-design tier for XL**: upstream issue #990 / PR #989 (merged
   before `ca1e85f`) document tier6b (20-24 GB) as "XL: no quantization needed, batch 2-4".
   `vector_quantize_pytorch 1.27.20` (required by the XL modeling code) is already pinned
   in `uv.lock`; `transformers<4.58` already satisfied.

Config changes this session:
- `app/catalog.py`: renamed `xl-sft-premium-4b-v1` -> **`xl-sft-quality-v1`**; VRAM floor
  `32000` -> **`15000`**; `planner_model` -> `None` (XL DiT is self-contained, no separate
  4B LLM planner is loaded); `tasks` trimmed to `text2music`/`cover`/`repaint`;
  multiplier 4.00 (provisional). Added the **`ace-step-1.5-xl-turbo`** selection with
  `xl-turbo-fast-v1`: CFG-distilled (guidance locked 1.0, 8 steps locked, DCW off),
  multiplier 2.00 (provisional).
- `app/config.py`: added **`OAL_XL_TURBO_CHECKPOINT_ID`** (default empty -> unconfigured).
- `scripts/run_house_workers.sh`: baseline worker now bind-mounts
  `/Cold-Archive/oal-models/acestep-v15-xl-{sft,turbo}` into `/opt/acestep/checkpoints/`
  and allowlists `sft-quality-v1,xl-sft-quality-v1,xl-turbo-fast-v1`, with the
  llama-server footprint shrunk via `OAL_LLM_CTX=4096` + `OAL_LLM_GPU_LAYERS=32` (frees
  ~1-2 GB). Static footprint ~13.7 GB leaves ~8 GB headroom on 24 GB for XL peaks.
- Both native XL checkpoints downloaded to `/Cold-Archive/oal-models/` (19 GB + 20 GB).
- Tests: profile shape/lock, provisional multipliers (2.0/4.0), provisioned quote+charge,
  and unconfigured-503 coverage for both XL selections (suite 248 passed).

Honest status: code + checkpoints + worker config are in place; XL remains `unconfigured`
(503) until the operator's live worker carries the new env and the checkpoint dirs, after
which a real 12 s XL-SFT + XL-Turbo render + `nvidia-smi` peak < 20 GB must be confirmed
before the multipliers are considered validated. The community merge still awaits an
operator-approved exact checkpoint/revision/license.

 ## 2026-10-20 — XL audio-validated on the 24 GB worker; offload REQUIRED (no-offload OOM)

 Live validation completed the entry above. On the shared 24 GB baseline worker
 (GPU0, NVIDIA RTX PRO 4000 Blackwell), real 12 s stereo renders were produced for
 **both** XL selections (peak `nvidia-smi` **19.7 GB / 24 GB**, `synthetic_test_audio=false`):
 - `ace-step-1.5-xl-turbo` (profile `xl-turbo-fast-v1`, engine `acestep-v15-xl-turbo`)
 - `ace-step-1.5-xl-sft` (profile `xl-sft-quality-v1`, engine `acestep-v15-xl-sft`)
 Turbo regression (global offload on) still renders, peak **11.2 GB**.

 The "no offload" plan assumption was refuted live. Without offload the **full engine
 process** (XL DiT ~10 GB bf16 + Qwen3 text encoder ~10 GB + VAE/embedding) peaked at
 **20.6 GiB**, which with the co-located llama-server (~2.85 GiB) + two CUDA contexts
 exceeded the 23.46 GiB card → CUDA OOM. `VRAM_AUTO_OFFLOAD_THRESHOLD_GB` is `20.0`,
 so a 24 GB card does not auto-offload. Fix (both in `run_house_workers.sh`):
 - `ACESTEP_OFFLOAD_TO_CPU=1` — DiT stays resident on GPU; text encoder/VAE load to
   GPU only while in use, then return to CPU (no perf hit). No quantization.
 - `OAL_LLM_GPU_LAYERS=0` — llama-server (Qwen3-4B) moved fully to CPU, freeing its
   ~2.85 GiB + CUDA context. (Supersedes the `OAL_LLM_GPU_LAYERS=32` line above.)

 Note: flash-attention is unavailable for XL on this card → SDPA fallback
 (`init_service_loader.py`), not a blocker.

 ## 2026-10-20 — int8 shipped; per-model denoising defaults raised; worker-control
 ## forwarding bug fixed

 Three things landed after the XL-on-24 GB validation.

 1. **int8 DiT quantization validated + shipped (all DiT models).** torchao
    `int8_weight_only` (pinned `_apply_dit_quantization`) loads cleanly on Blackwell
    sm_120 ("DiT quantized with: int8_weight_only", no kernel errors). Same-seed A/B
    int8-vs-bf16 (nondeterminism floor is 0 — a same-seed repeat was byte-identical):
    turbo SNR 19.5 dB / Pearson 0.996; sft 13.1 / 0.977; XL-Turbo 23.7 / 0.998;
    XL-SFT 12.0 / 0.969; loudness shift < 0.5 dB. Weight-only int8 keeps activations
    bf16 → only subtle HF detail loss, no structural change; fp8 not required. Worker
    env `ACESTEP_QUANTIZATION=int8_weight_only` (+ `ACESTEP_OFFLOAD_TO_CPU=1`,
    `OAL_LLM_GPU_LAYERS=99`) returns the lyrics llama-server to GPU (style-prompt
    0.46 s, full lyrics draft 4.6 s) with XL steady peak **~13.5 GB / 24 GB**.
    **Correction** to the entry above: the Qwen3 text encoder is **1.2 GB**
    (`gpu_config.py:154` `"text_encoder": 1.2`), NOT 8-10 GB; the 20.6 GiB no-offload
    footprint was DiT(9) + activations + CUDA/fragmentation + llama.

 2. **Per-model denoising defaults aligned to upstream.** Non-turbo guidance had
    been set 2.0-3.0, far below the engine's `guidance_scale` default 7.0 (docs
    "typical 5-9", best-quality 7-9). New: sft 64 steps (50-100)/CFG 7.0/shift 1.0;
    xl-sft 100 steps/CFG 7.0/shift 1.0; merge 64/CFG 7.0/shift 1.0/DCW off.
    Turbo-family stays 8 steps/CFG 1.0/shift 3.0; xl-turbo DCW flipped to on (matches
    2B turbo default). `shift` is now a profile-owned band surfaced in
    `control_schema` + `/model-selections` and forwarded. Verified upstream:
    **quantization and denoising are independent** — nothing ties int8 to steps/
    guidance; this is correctness, not int8 compensation.

 3. **Worker-control-forwarding bug (the real reason the settings matter).**
    `engine_worker._payload_for` read raw `request["controls"]` (empty when users omit
    optional controls) instead of the API's `_admission["resolved_controls"]`, so the
    engine fell back to its REST default `inference_steps=8` for EVERY model — the
    profile steps/cfg/shift were computed at admission but never sent. Fixed to
    forward resolved controls (raw as legacy fallback). Verified live: xl-sft ran
    **100/100**, sft **64/64**, turbo stayed 8. (`sampler_mode` euler/heun is genuinely
    absent from the pinned REST `release_task_models`, so it stays correctly rejected.)

 Deploy: hub backend rebuilt at `a95d4fb` (image `denoise-a95d4fb`) serving the new
 catalog; worker image `stratastack/oal-worker:house-v1-070-int8` bakes the int8 patch
 via `Dockerfile.worker_int8` (thin overlay on the current base; the same patch is
 `git apply`+grep-guarded into `Dockerfile.worker` for from-source builds). The
 transitional bind-mount is removed. Tests 250 pass.

 ## 2026-10-20 — website Quality-band fix + Vast int8/XL enablement

 - **Frontend (f68274b):** the create form used a hard-coded Quality ladder [8,16,32]
   that predates the per-profile step bands. Choosing "Balanced(16)"/"Fine(32)" on a
   50-100 premium model sent an out-of-band value → the strict backend correctly
   returned "inference_steps out of range". `generation.ts` now takes the selected
   profile's `control_ranges` and emits steps/guidance/shift only when in-band and
   differing from the profile default (locked profiles never emit; shift=1 is treated
   as "unset"); `CreateWidget` renders a band-driven Quality slider and resets it on
   model switch. Backend left strict (correct contract); vitest 17 pass; served SPA
   rebuilt/redeployed (asset `index-CgAawNpF.js`).
 - **Vast int8/XL (d837c9c, df63768):** published `house-v1-070-int8` + a lighter
   `ca1e85f-torch2.10-cu128-wg-int8` overlay to Docker Hub (the local-only int8 image
   was previously unbacked-up). `autoscale.py::worker_env` gives engine nodes the
   premium/XL env (`ACESTEP_QUANTIZATION=int8_weight_only`, `ACESTEP_OFFLOAD_TO_CPU=1`,
   `OAL_PREMIUM_PROFILES_ENABLED`, XL checkpoint ids; gated by `OAL_VAST_PREMIUM`), and
   `OAL_VAST_DISK`→160 for on-demand HF checkpoint download (Vast can't bind-mount).
   Chose the house-based image because Vast autostarts the HF-unavailable merged
   `acestep-v15-house-turbo` (light base would break the default model). Nodes already
   ≥24GB via `pick_offer`; profiles self-gate on `vram_required_mb`.
 - **Live validation:** launched one paid RTX 3090 (24576 MB) via `create_instance`; it
   pulled `house-v1-070-int8`, booted the int8 engine, fetched the bundle, and
   registered as a live worker (`acestep-31d478eb18c1-92`) before auto-destroy
   (`finally` guard). Autoscaler service restarted with the new image+env.
 - **Secrets hygiene:** the Docker Hub PAT and (incidentally) the ssh push key /
   secret-key were surfaced in-session; **rotate the `stratastack` PAT** and treat the
   push key as exposed.

 ## 2026-10-21 — premium audio root-caused: the disabled 5 Hz lyric-LM (not int8/LLM)

 The earlier "only turbo is usable; SFT garbled; XL crashes" was NOT the int8/llama/memory
 thread I first chased. Listening-driven root cause, per checkpoint:

 1. **SFT/XL noise-wash = missing planner.** OAL runs with `ACESTEP_INIT_LLM=false` +
    global `thinking=false` → the 5 Hz audio-code "blueprint" never ran; the DiT had only
    text conditioning. The engine's own comment (`padding_utils.py:78`, issue #929) says
    exactly this yields garbage, worse with duration. My `shift=1.0` (from the "training
    uses 1.0" note) compounded it — serving wants **shift 3.0** + ADG (per INFERENCE.md
    best-quality). Fix: per-job `use_cot`+`lm_model_path` for premium (`build_payload`),
    shift→3.0, `use_adg`, verbatim lyrics kept (`use_format=false`; `inference.py:833`
    restores user lyrics). Verified: SFT 240 s flat 0.33→0.17, envCV 0.19→0.43 — clean.
 2. **XL "crash" was a LoRA mismatch, not OOM.** The mood→auto-LoRA (2 B base
    `ace-step-1.5`) was force-loaded onto the 4 B XL DiT → `PeftModel` state_dict error →
    MAX_ATTEMPTS. Fixed with `_lora_compatible` (skip cross-family adapters, keep style
    tags, render anyway) + non-fatal `load_lora`. XL peak was ~20 GB — never a memory issue.
 3. **XL planner genuinely needs the VRAM → int8 only for XL.** bf16 XL-SFT + 1.7 B planner
    OOMs at 120 s (~24 GB), so the baked int8 patch is gated to `config_path` containing
    `xl`; turbo/SFT stay bf16 (their compatible LoRAs load). XL-SFT 120 s then succeeds
    (peak ~20 GB). Also: the "int8 byte-identical" I saw earlier was Pass B running with
    `ACESTEP_COMPILE_MODEL=1` — quantize-after-compile FQNs are `_orig_mod.decoder…` so the
    `"decoder"` filter no-ops; with compile OFF int8 truly applies.
 4. **Drafting LLM to its own CPU worker.** Moved Qwen3-4B llama-server off the GPU card
    to a separate CPU container (`oal-llm`, `--n-gpu-layers 0`) on ai-server01. Chose
    ai-server01 over the hub after a real speed test: hub is a 2010 Xeon VM, load 16,
    drafts ~15-20 s style / 120 s (timeout); ai-server01 (32-core Threadripper) does style
    in ~1.4-2 s. Backend `llm_base_url` repointed to `http://10.203.0.2:8082/v1`.

 Worker: init_lm=true, LM backend pt + 1.7 B, int8 (XL-gated), offload; premium/Vast get
 the same. Commits d4e1acc/a1df04f/d8fcd1a/a755ced; 256 tests. Still open: the two users'
 failed XL jobs can now be retried (LoRA skipped + int8 XL); and the earlier XL int8 note
 in gpu_config/docs says compile "required for quantization" which is the opposite of what
 actually happens (compile breaks it) — flagged, not yet corrected upstream-side.

## 2026-10-21 — UAIS milestones A–D + Vast training worker (branch feat/uais-artist-voice)

Decisions:
1. **Hard replace, no migration.** The old rights/dataset/training-run/evaluation stack was
   experimental with no customers; migration 0033 drops those tables and creates the six
   UAIS tables. `artist_profiles.default_voice_profile_id` replaces `active_version_id`;
   `loras.adapter_id` replaces `profile_version_id`.
2. **No LLM in the voice path.** QC (ffmpeg), embeddings (`mfcc-stats-v1`, pure-Python
   log-mel stats) and validation similarity are deterministic; the embedding is an analysis
   artifact only, never a conditioning input. Threshold 0.5 is a calibration default.
3. **Capability manifests fail closed.** Only `ace-step-1.5-turbo` has
   `adapter_load_verified=true`; SFT/XL/merge report honest unverified states; unknown
   selections get `UNSUPPORTED`, never silent routing.
4. **DB is truth.** Voice jobs ride the durable job system (`voice.analyze/train/validate`);
   queue keys `oal:queue:training[-xl]` are delivery hints. Credits (50/10) charged at
   admission, refunded by the worker on failure via `voice-refund:{job}`.
5. **Vast training = slim image + runtime download**, two autoscaler pools (2B on default
   offers; XL on ≥32 GB / ≤$0.60 dph), queue-pinned via `OAL_TRAIN_(XL_)QUEUE_MODEL_ID`;
   `dph_total` recorded to `vast_instances.dph` for cost accounting.

Validation evidence: backend suite 284 passed (13 UAIS API tests in tests/test_artist.py;
autoscale pool tests in tests/test_autoscale.py); frontend `tsc -b && vite build` clean and
vitest 17 passed. Commits 56c188e (backend), f35498f (Vast worker), 2c32f23 (frontend+docs).
Still open: real-GPU training run (first XL VRAM/time benchmark), SVC/VIPE phase E,
genre-independence phase F, and owner review before merge.
