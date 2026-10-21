# Changelog

All notable changes to the OpenAudioLab backend implementation. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Implementation lives on
feature branches; `master` remains the documentation/planning baseline until the
owner approves a merge. Per-milestone acceptance records are in `docs/MILESTONE_N.md`.

## [Unreleased]
### GPU Orchestration run (2026-10-21, feat/gpu-orchestration)
- **Smart Model Queue Manager:** peek-window model-affinity job selection over the
  shared queue (claim-then-LREM, Postgres authoritative), immediate cross-model
  switch on loaded-group exhaustion (no 600 s idle-stop wait), fairness batch/aging
  caps; `workers.loaded_model` (migration 0036).
- **Swappiness (0–100, default 50):** explainable local-vs-remote provisioning
  decisions logged to `gpu_scale_decisions`; fleet settings persisted + validated
  (`PATCH /admin/gpu-fleet/settings`); autoscaler reads DB settings.
- **Offer discovery:** `app/vast_offers.py` REST search with hard filters and a
  documented weighted ranking; Top-10 admin endpoint with 30 s server cache and
  "Not reported" for missing provider fields.
- **Unified provisioning:** durable `gpu_deployments` intents (idempotent,
  offer-revalidated, budget-guarded), autoscaler as sole Vast CLI owner, manual
  workers immune to routine scale-down, worker stop/restart/destroy API with
  busy guard, costs + fleet events (migration 0037).
- **GPU Fleet console:** Admin → GPU Fleet (Overview / Smart Queue / Settings /
  Top-10 Offers + deploy flow / Deployments / Instances / Costs / Events).

### Remediation Phase 6 (2026-10-21, feat/uais-artist-voice)
- **Artist UX (R19):** inline name/bio editing on artist rows; consent checkbox now
  gates recording upload in Voice Studio; per-profile deep link into Voice Studio.
- **Voice state visibility (R20):** Create widget shows the bound artist's per-model
  adapter state (applied / stale / no adapter / wrong model / unavailable) before submit.

### Remediation Phase 5 (2026-10-21, feat/uais-artist-voice)
- **Creator (R16):** pre-submit premium price preview (`≈ N credits`, debounced,
  pricing-fields only), draft writes debounced to ≤1/s, cross-tab draft sync via
  `storage` events.
- **Library (R17):** title search, sort, 25-per-page pagination over a 200-track fetch;
  rows reduced to play/♥/Share + `⋯` overflow menu (downloads, stems, details, remix,
  repaint, workspace move).
- **Mobile (R18):** hamburger nav toggle at ≤768 px; compact player bar on small screens.

### Remediation Phase 4 (2026-10-21, feat/uais-artist-voice)
- **Claim-time capability check (R14):** engine workers re-verify the job's execution
  profile (allowlist, installed checkpoint, free VRAM) after claiming and release
  incompatible jobs without burning the attempt budget — no more turbo/premium
  requeue-loop on a mixed fleet.
- **Dead `gpu_leases` table dropped** (migration 0035); serialized claiming is the
  GPU-ownership mechanism.
- **Workload-aware autoscale (R15):** scale decisions use estimated queued GPU-seconds
  (duration x model-class factors, provisional pending XL benchmark) instead of raw
  queue depth, with depth-only fallback.

### Remediation Phases 1–3 (2026-10-21, feat/uais-artist-voice)
- **P0 job safety:** retryable failures requeue with capped backoff (`jobs.next_retry_at`),
  terminal failure refunds generation credits (explicit retry re-charges), upstream ACE-Step
  task id persisted per attempt (`job_attempts.upstream_task_id`) and repolled after worker
  restarts, stranded-queued sweeper + retry-window publish eligibility (migration 0034).
- **P1 worker/GPU recovery:** engine quarantine after unhealthy failures, engine restart
  after stalls, audio-worker heartbeat thread, compose restart policies + worker healthcheck
  disables, autoscale $0.40/day cap, persistent state file, mid-job scale-down drain hold.
- **P2 UI correctness:** `GET /tracks/stats` + plan `allowance` in `/auth/me`; sidebar
  active-state/dedupe, endpoint-backed stats, plan-based credit denominator, honest
  indeterminate progress bars, humanized stage labels, widget Retry button, persisted job
  tracking, focus-visible + reduced-motion styles, accessible notification bell.

### UAIS: Universal Artist Identity System replaces experimental artist training (2026-10-21)
- **Hard replace** of the rights/dataset/training-run/evaluation stack (migration 0033 drops
  the old experimental tables; no customer data existed). New tables: `voice_profiles`,
  `voice_datasets`, `voice_recordings`, `voice_dataset_versions`, `voice_adapters`,
  `voice_analyses`.
- **Voice pipeline API** under `/artist-profiles/{id}/voice/*`: dataset create/get, recording
  upload (ffmpeg QC + SHA-256 dedupe) / delete, version freeze (adapters go `stale`),
  `analyze` / `train` (50 cr) / `validate` (10 cr) jobs, `status`, per-model
  `compatibility`, `adapters`, `adapters/capabilities`, voice-profile list/patch/set-default.
- **Generation binding**: `artist_id` + `voice_fidelity` (`native|reference|best`) or explicit
  `voice_adapter_id` (mutually exclusive with `lora_id`); resolved plan frozen into the job;
  reference plans run `task_type=cover` with the artist reference asset. No silent fallback.
- **Capability registry**: per-model voice manifests; only turbo is adapter-load-verified;
  unknown models fail closed (`UNSUPPORTED`), never silently routed.
- **Vast training worker**: `training_worker` role runs voice jobs; autoscaler gains a 2B pool
  (`oal:queue:training`) and an XL pool (`oal:queue:training-xl`, ≥32 GB offers, dph cap);
  nodes are queue-pinned and `dph` is recorded for cost accounting.
- **Frontend**: new Voice Studio page (`/voice`), create widget binds the workspace artist's
  default adapter when model-compatible, Training page lists voice jobs, Admin training/LoRA
  surfaces moved to job-id/adapter-id.
- **Phases E/F**: `voice.analyze` separates vocal stems per recording when a worker separator
  exists (stored as derived `training_stem` assets; `input_type: vocal_stem`, honest
  `full_mix` fallback), and writes a genre-independence **estimate** (cross-recording
  embedding consistency) into `voice_profile.identity_json`.

### My Tracks UX, workspaces, FAQ, and test-data cleanup (2026-10-21)
- **Details** card now shows formatted generation info (model/engine/planner, task, duration,
  seed, lyrics origin+hash, prompt/idea/style, controls, cover/repaint source, created) with
  "Reuse recipe" + "Copy raw" instead of a JSON dump.
- **Stems** export now produces a single ZIP (stems/*.wav + manifest.json); `/stems` returns a
  `zip` and new `/stems/zip` serves the stored zip or builds one on demand; UI has one
  "All stems (.zip)" button + optional individual links.
- **Workspaces**: real asset membership (`assets.workspace_id`, migration 0029) with an
  always-present, protected **"My Default Space"** per owner (backfilled); My Tracks workspace
  filter chips; per-track move; create/rename/delete (delete reassigns to default); recipe-save
  files the asset too.
- **FAQ** page at `/faq` (models/tiers, workspaces, artist LoRA/training, lyrics, credits,
  durations) + nav/footer.
- **My Tracks overflow** fixed (base `.card`/`.track-row` wrap + shrinkable meta/actions; the
  row no longer escapes its box at 1100–1900px).
- **Cleanup**: hard-cascaded 21 test/seed accounts (xl-admin test + `test@` + disabled
  `journey-*`) via `scripts/purge_users.py` (dry-run→execute) and reclaimed their storage dirs.

### Generation quality: 5Hz-LM planner for premium, LoRA compatibility, XL int8, drafting LLM to CPU (2026-10-21)
- **Root-caused "SFT/XL garbled, only turbo usable."** Premium (SFT/XL) audio was a noise-wash
  because the **5 Hz lyric-LM planner was disabled** (`ACESTEP_INIT_LLM=false` + global
  `thinking=false`) — the DiT had no duration-locked audio-code blueprint (engine issue #929) —
  compounded by `shift=1.0`. Now enabled **per-job for premium** (`use_cot` + `lm_model_path`
  through `build_payload`; `use_format=false` keeps user lyrics verbatim). Non-turbo **shift
  → 3.0**, + **`use_adg`**, steps/CFG as set. Verified: SFT 240 s spectral-flatness 0.33→0.17,
  envelope-CV 0.19→0.43.
- **XL "crash" was a LoRA/architecture mismatch, not OOM.** The mood/auto-LoRA (2 B base
  `ace-step-1.5`) was force-applied to the 4 B XL DiT → PeftModel `state_dict` error →
  MAX_ATTEMPTS. Added `_lora_compatible` (skip cross-family LoRAs, keep style tags, render
  anyway) + non-fatal `load_lora` guard. Turbo/SFT (bf16) keep their compatible LoRAs.
- **XL memory:** even with the 1.7 B planner, bf16 XL-SFT 120 s OOMs on 24 GB, so int8 is
  now **gated to XL only** (`config_path` contains `xl`) in the baked worker patch — turbo/SFT
  stay bf16 (their 2 B LoRAs load). XL-SFT 120 s then renders (peak ~20 GB vs 24 GB cap).
- **Drafting LLM moved to its own CPU worker.** Qwen3-4B llama now runs as a separate CPU
  container (`oal-llm`, `--n-gpu-layers 0`) on ai-server01, freeing the GPU worker for
  DiT+planner. The hub VM was rejected after a speed test (15–20 s style / 120 s lyrics ≈
  timeout); ai-server01's 32-core Threadripper does style in ~1.4–2 s.
- Kept the earlier worker fixes: heartbeat-across-setup + attempt-heartbeat leak stop +
  resolved-controls forwarding. Vast premium nodes get the same planner/int8/pt env.

### Vast remote workers: int8 image + XL/SFT premium capability (2026-10-20)
- Published the int8 worker images to Docker Hub (`house-v1-070-int8`, and a lighter
  `ca1e85f-torch2.10-cu128-wg-int8` overlay), backing up the previously local-only artifact.
- `autoscale.py`: engine Vast nodes now get `ACESTEP_QUANTIZATION=int8_weight_only`,
  `ACESTEP_OFFLOAD_TO_CPU=1`, `OAL_PREMIUM_PROFILES_ENABLED`, and the XL checkpoint ids
  (gated by `OAL_VAST_PREMIUM`); `OAL_VAST_DISK` raised to 160 for on-demand HF downloads
  of the XL/SFT checkpoints (Vast can't bind-mount). Nodes already ≥24 GB via `pick_offer`.
- Chose `house-v1-070-int8` (not the light base) because Vast autostarts the HF-unavailable
  merged `acestep-v15-house-turbo`. Validated: a launched RTX 3090 pulled the int8 image,
  booted, and registered as a live worker before teardown.

### int8 DiT quantization + corrected per-model denoising defaults (2026-10-20)
- **int8 ships (all DiT models).** The engine's env-gated patch (pinned `_apply_dit_quantization`)
  was validated on Blackwell sm_120: `ACESTEP_QUANTIZATION=int8_weight_only` halves the
  XL DiT resident (~9→~4.5 GB), letting the lyrics llama-server return to GPU
  (`OAL_LLM_GPU_LAYERS=99`) with XL steady peak **~13.5 GB / 24 GB** (real 12 s stereo
  renders for XL-Turbo/XL-SFT/turbo/sft). Same-seed A/B int8-vs-bf16: SNR 19.5/13.1/
  23.7/12.0 dB (turbo/sft/XL-Turbo/XL-SFT), Pearson 0.97-0.998, loudness shift < 0.5 dB
  → accepted, fp8 not required. The int8 patch is baked into the worker image
  (`Dockerfile.worker` `git apply` + grep guard; `Dockerfile.worker_int8` thin overlay).
  Corrected an earlier mis-statement: the Qwen3 text encoder is **1.2 GB** (`gpu_config.py:154`),
  not 8-10 GB.
- **Per-model denoising defaults raised to upstream** (they were under-set): non-turbo
  guidance was 2.0-3.0 vs the engine default 7.0. Now sft 64 steps (50-100)/CFG 7.0
  (5-9)/shift 1.0; xl-sft 100/CFG 7.0/shift 1.0; merge 64/CFG 7.0/shift 1.0/DCW off;
  turbo-family stays 8 steps/CFG 1.0/shift 3.0; xl-turbo DCW flipped on (match 2B turbo).
  `shift` exposed as a profile-owned control band.
- **Fix: worker now forwards the profile-resolved controls.** `_payload_for` read raw
  `request["controls"]` (usually empty) instead of `_admission["resolved_controls"]`, so
  the engine ran at its REST default `inference_steps=8` for every model and the
  per-model steps/cfg/shift never applied. Now resolved controls are forwarded (raw kept
  as legacy fallback); verified xl-sft 100/100 and sft 64/64 steps in the engine log.
  Tests: 250 passed.

### XL (4B DiT) premium models provisioned on the 24 GB baseline worker (2026-10-20)
- Corrected the earlier "XL needs a dedicated ≥32 GB worker" assumption: XL is a
  first-class model in the pinned engine (`ca1e85f`, upstream issue #990 / PR #989).
  The 4B DiT loads **~9 GB in bf16** (upstream `MODEL_VRAM["dit_xl_base"]=9.0`), but
  the **full engine process** (DiT + Qwen3 text encoder + VAE/embedding) peaks at
  **~20.6 GiB without offload**, which OOMs a 24 GB card once the co-located
  llama-server is counted. XL therefore runs with **`ACESTEP_OFFLOAD_TO_CPU=1`**
  (DiT stays resident on GPU; text encoder/VAE load to GPU only while in use, then
  return to CPU — no perf hit) **and** the llama-server moved fully to CPU
  (`OAL_LLM_GPU_LAYERS=0`), freeing its ~2.85 GiB. No quantization. Audio-validated:
  XL-Turbo + XL-SFT peak **19.7 GB / 24 GB**, Turbo (regression) 11.2 GB. Note:
  flash-attention is unavailable for XL on this card → SDPA fallback.
- Renamed the XL-SFT premium profile `xl-sft-premium-4b-v1` → `xl-sft-quality-v1`;
  VRAM floor lowered `32000` → `15000`; `planner_model` set to `None` (the XL DiT is
  self-contained; no separate 4B LLM planner is loaded); `tasks` trimmed to
  `text2music`/`cover`/`repaint`; multiplier **4.00** (provisional).
- Added the `ace-step-1.5-xl-turbo` selection with `xl-turbo-fast-v1` profile:
  CFG-distilled (guidance locked 1.0, 8 steps locked, DCW off), multiplier **2.00**
  (provisional), mirroring `turbo-fast-v1`'s lock behavior at XL fidelity.
- New `OAL_XL_TURBO_CHECKPOINT_ID` setting alongside `OAL_XL_CHECKPOINT_ID`; both
  default empty so the profiles stay `unconfigured` (503) until provisioned.
- Worker script bind-mounts `acestep-v15-xl-sft` + `acestep-v15-xl-turbo` and
  allowlists both premium profiles on the baseline worker.
- Tests: profile shape/lock, provisional multipliers, provisioned quote+charge, and
  unconfigured-503 coverage for both XL selections (suite 248 passed).

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

### Roadmap Phase 1 — Model capability registry + control validation (2026-10-20)
- `app/registry.py` is now the single capability source: structured control specs
  (type/range/default/label/unit/model-family applicability) plus per-model
  `supported_task_types` and `model_family`.
- API now validates control **values** (range/type) with `CONTROL_INVALID` + per-field
  details, and rejects base-only `shift` on the Turbo release as `CONTROL_UNSUPPORTED`
  (no longer accepted-but-ineffective). Strict unknown-control rejection preserved.
- `time_signature` is accepted, forwarded by the adapter, and captured in the durable
  manifest; surfaced in Studio recreation.
- `GET /models/{id}` exposes `controls` metadata, `supported_task_types`, and
  `model_family`; the frontend serializer is capability-driven (filters to the model's
  supported set, keeps intentional `shift:0`, exact-lyrics + real provenance).
- Added a real frontend test runner (`vitest`) with 9 serializer tests across modes.
- Tests: backend 212 passed; frontend `vitest` 9 passed; `tsc -b && vite build` clean.

### Roadmap Phase 2 — source-conditioned cover/repaint (backend) (2026-10-20)
- `GenerateJobRequest` gains typed `task_type`, `src_asset_id`, `reference_asset_id`,
  `audio_cover_strength`, `cover_noise_strength`, and repaint fields (bounds/mode/strength/chunk_mask).
- `jobs.py` validates task support against the model release (`TASK_UNSUPPORTED`), requires an
  owned source for cover/cover-nofsq/repaint (`SOURCE_REQUIRED`), enforces asset ownership
  (`SOURCE_NOT_FOUND` / `SOURCE_INVALID`), and repaint region bounds (`SOURCE_REGION_INVALID`) —
  no reservation on rejection.
- `engine_worker` stages the owner's source audio to a content-hashed file under the engine-allowed
  temp dir (`OAL_ASSET_STAGE_DIR`, default `/tmp/oal-asset-stage`) and forwards `src_audio_path` /
  `reference_audio_path` / `task_type` / cover + repaint fields via `build_payload`.
- Durable manifest captures task_type/src/reference/cover/repaint lineage.
- Engine-verified on the deployed Turbo model at ca1e85f: a real cover with a staged source produced
  source-honored audio (the engine only accepts temp-dir or relative source paths — not absolute
  paths elsewhere).
- Engine-verified on the deployed Turbo model at ca1e85f: a real cover with a staged source produced
  source-honored audio (the engine only accepts temp-dir or relative source paths — not absolute
  paths elsewhere).
- Studio UI: a per-track "✦ Remix" action submits a real `task_type=cover` job that references the
  take's owned `src_asset_id` and a user-entered target style (via the canonical serializer), with
  inline status/error; covers surface in the live queue. Serializer `vitest` extended (11 tests).
- extract/lego/complete remain base-family only (out of scope for the Turbo worker).

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
