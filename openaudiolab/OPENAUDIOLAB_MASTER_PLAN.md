# OpenAudiolab Master Plan

**Version:** 0.1.0-foundation  
**Last Updated:** 2026-05-22

---

## Source of Truth Declaration

This file is the single source of truth for OpenAudiolab development.

All human developers and AI development agents must follow this file.

If another instruction, TODO, issue, generated plan, or agent decision conflicts with this file, this file wins unless it has been intentionally updated.

Any architecture change, pipeline change, worker behavior change, storage behavior change, security change, model-pack change, community/commercial boundary change, or development governance change must be reflected here before implementation proceeds.

---

## 1. Project Identity

- **Name:** OpenAudiolab.io
- **Type:** Open-source music creation platform
- **Editions:** Free Community Edition + Paid Commercial Edition (future)
- **Current Version:** 0.1.0-foundation
- **Repository Root:** `openaudiolab/`
- **Source of Truth:** This file (`OPENAUDIOLAB_MASTER_PLAN.md`)
- **Agent Instructions:** `AGENTS.md`
- **Development Log:** `DEVELOPMENT_LOG.md`
- **Manifest:** `openaudiolab.manifest.json`

## 2. Current Build Priority

**Priority:** Backend job orchestration, worker execution, storage, security, and test frontend.

The immediate goal is NOT a polished Suno/Udio-style user experience. The immediate goal is:
- Secure first-run setup
- Backend job orchestration with real state machine
- Worker container architecture (local + remote)
- Storage abstraction with retention
- CPU-safe test generation
- ZIP export pipeline
- Simple test frontend with job progress page
- Development logging discipline

## 3. Non-Negotiable System Requirements

1. Secure first-run setup required before any public usage
2. No default production credentials shipped
3. Worker registration requires token
4. Generated files are private by default
5. Default 7-day file retention
6. Custom lyrics are preserved exactly as submitted
7. Lyric reasoning runs for AI-generated lyrics
8. Storage is adapter-based (local, minio, s3_compatible)
9. Workers use unified protocol (local and remote)
10. Backend is model-agnostic; no single model hardcoded
11. Cloud GPU support via Vast.AI and RunPod abstractions
12. DEVELOPMENT_LOG.md must be updated for every task

## 4. Runtime Modes

### No-GPU Backend Mode
- Runs on servers without GPUs
- Backend, database, Redis, storage, frontend all work
- Worker registration, job creation, cloud dispatch work
- Local generation disabled
- CPU-only 15-second test generation works
- UI shows: "Local generation unavailable. No compatible GPU with required VRAM was detected."
- No-GPU mode is NOT an error state

### Local GPU Mode
- Available only when NVIDIA GPU detected
- CUDA must be available
- Minimum 12 GB VRAM required
- Required model pack must be installed
- Worker runtime must be healthy and registered
- Low-VRAM systems: load one model at a time, unload before next stage

### Remote Cloud GPU Worker Mode
- Same worker protocol as local workers
- Provider targets: Vast.AI, RunPod
- Cloud provider abstraction layer; no hardcoded provider logic in job stages
- Provisioning requires explicit configuration and enablement

## 5. Secure First-Run Setup

- On startup, backend checks if setup is complete
- If no admin exists, system enters first-run setup mode
- Frontend redirects to `/setup`
- Normal app usage is limited until setup completes
- Worker registration requires configured token
- Cloud providers remain disabled until explicitly enabled
- Setup collects: admin email, password, site name, public backend URL, storage provider, retention days, worker token, CPU test mode, cloud workers toggle
- Backend stores: `setup_completed=true`, `setup_completed_at`, `initial_admin_created=true`
- After setup: `/api/setup/initialize` refuses to run again, `/setup` shows "already completed"
- Additional admin creation requires authenticated admin action
- Passwords hashed with bcrypt/argon2; never stored plaintext, never logged, never exposed
- Minimum 12 characters; rejects common placeholders (admin123, password, changeme, test123, etc.)
- No production credentials like admin@openaudiolab.io/admin123, admin/password, test/test
- Dev-only credentials only if `APP_ENV=development` AND `SEED_DEV_ADMIN=true`

## 6. Backend Architecture

- **Framework:** FastAPI (Python)
- **Database:** PostgreSQL
- **Queue:** Redis
- **Storage:** Adapter-based (local, minio, s3_compatible)
- **Auth:** JWT-based with bcrypt password hashing
- **Logging:** Structured logs (backend, worker, per-job pipeline)

### API Routes
```
GET    /api/health
GET    /api/setup/status
POST   /api/setup/initialize

POST   /api/auth/login
POST   /api/auth/logout
GET    /api/auth/me

GET    /api/system/status

POST   /api/jobs
GET    /api/jobs
GET    /api/jobs/{job_id}
POST   /api/jobs/{job_id}/cancel
POST   /api/jobs/{job_id}/retry
GET    /api/jobs/{job_id}/logs
GET    /api/jobs/{job_id}/download

GET    /api/workers
POST   /api/workers/register
POST   /api/workers/heartbeat
POST   /api/workers/request-job
POST   /api/workers/jobs/{job_id}/stage-update
POST   /api/workers/jobs/{job_id}/complete
POST   /api/workers/jobs/{job_id}/fail

GET    /api/models
GET    /api/storage/assets

GET    /api/settings
PATCH  /api/settings
```

### API Security Defaults
- CORS restricted by environment variable
- Request size limits
- Basic rate limiting placeholder
- Secure headers placeholder
- Environment-aware debug mode
- No stack traces in production
- Secrets loaded from environment only
- No real secrets committed

### Production Startup Warnings/Failures
- SECRET_KEY is default
- JWT_SECRET is default
- WORKER_REGISTRATION_TOKEN is default
- Storage credentials missing when cloud storage selected
- Setup incomplete and app appears publicly exposed

## 7. Job State Machine

### Job States
`created` → `queued` → `waiting_for_worker` → `provisioning_worker` → `assigned` → `running` → `stage_completed` → `uploading_results` → `completed`

Terminal states: `failed`, `cancelled`, `expired`

### Stage States
`pending` → `running` → `completed` (or `failed`, `skipped`)

### Default Pipeline Stages
1. `job_intake`
2. `prompt_validation`
3. `lyrics_generation_or_ingestion`
4. `lyrics_structure_validation`
5. `lyrics_reasoning`
6. `lyrics_revision`
7. `lyrics_humanization`
8. `composition_planning`
9. `audio_generation`
10. `daw_processing`
11. `effects_processing`
12. `mastering`
13. `preview_waveform_generation`
14. `zip_export`
15. `storage_upload`
16. `signed_download_url`
17. `retention_cleanup`

Stages may be skipped based on lyrics_mode and job configuration.

### Job Request Schema
```json
{
  "prompt": "string",
  "genre": "string",
  "mood": "string",
  "lyrics_mode": "ai|provided|hybrid|instrumental",
  "provided_lyrics": "string|null",
  "instrumental": false,
  "duration_seconds": 90,
  "vocal_mode": "string",
  "quality": "draft|standard|high|studio",
  "lyric_reasoning_mode": "off|fast|balanced|strict|studio",
  "dispatch_preference": "auto|local|remote_worker|cloud_gpu|cpu_test",
  "storage_retention_days": 7
}
```

## 8. Music Generation Pipeline

The pipeline executes sequentially through stages. Each stage reports its status to the backend. The backend tracks overall job progress.

- Stage implementations may be placeholders in early versions
- State machine must be real from the start
- CPU test generation validates the full pipeline without GPU requirements
- Real model integration comes after pipeline orchestration is proven

## 9. Custom Lyrics Pass-Through Rule

**Non-negotiable:** When `lyrics_mode=provided`, the system MUST preserve the user's lyrics EXACTLY as submitted.

The system must NOT:
- Automatically rewrite lyrics
- Humanize lyrics
- Correct grammar
- Change rhymes
- Change section order
- Remove lines
- Add lines
- Replace words
- Improve cadence
- Change spelling
- Sanitize style (unless legally/safety required)

User-provided lyrics are intentional creative input.

### Provided Lyrics Pipeline
1. Prompt/style request
2. User-provided lyrics
3. Structure validation only (non-mutating)
4. Composition planning
5. Audio generation
6. DAW processing
7. Effects
8. Mastering
9. ZIP export

Skip: `lyrics_generation`, `lyrics_reasoning`, `lyrics_revision`, `lyrics_humanization`

**Invariant:** `final_lyrics == provided_lyrics`

### Custom Lyrics Metadata
```json
{
  "lyrics_mode": "provided",
  "lyrics_mutated": false,
  "lyrics_generation_skipped": true,
  "lyrics_humanization_skipped": true,
  "lyrics_revision_skipped": true,
  "structure_validation_only": true
}
```

### ZIP Layout for Custom Lyrics
```
/lyrics
  user_provided_lyrics.txt
  lyrics_structure_report.json
```

Do NOT create misleading `lyrics_humanized.txt` for untouched custom lyrics.

### Frontend Display for Custom Lyrics
"Custom lyrics will be used exactly as written. OpenAudiolab will not rewrite, humanize, or correct them automatically."

## 10. Lyric Reasoning Rules

For AI-generated or hybrid lyrics, `lyrics_reasoning` is a real pipeline stage.

### Checks
- Prompt match
- Narrative coherence
- Hallucinated real-world facts/names/places/events
- Genre fit
- Singability
- Overused generic AI phrasing
- Section usefulness
- Chorus/hook strength

### Modes
- `off`, `fast`, `balanced`, `strict`, `studio`
- Default: `balanced`
- Default minimum passing score: 80
- Default max revision attempts: 3

### Report Format
```json
{
  "passed": true,
  "score": 86,
  "mode": "balanced",
  "issues": [],
  "recommended_action": "continue"
}
```

### ZIP Layout for AI Lyrics
```
/lyrics
  lyrics_original_ai.txt
  lyrics_humanized.txt
  lyrics_quality_report.json
```

## 11. Worker Container Architecture

Workers are a unified runtime. Local GPU workers and remote cloud workers use the same protocol.

### Worker Images
- **worker-lite:** CPU test pipeline, development, CI testing. No heavy model weights.
- **worker-gpu-base:** GPU-capable runtime without baked-in heavyweight model weights. CUDA/PyTorch placeholder.
- **worker-community-full:** Official batteries-included Community Edition GPU worker. Only models passing redistribution checks.
- **worker-studio-full:** Large high-quality worker for cloud GPUs and commercial installations. 24 GB VRAM minimum.

### Worker Environment Variables
- `BACKEND_URL`
- `WORKER_REGISTRATION_TOKEN`
- `WORKER_NAME`
- `WORKER_MODE`
- `MODEL_PACK_PATH`
- `WORKER_VERSION`

### Worker Protocol
1. Startup and config loading
2. GPU/VRAM/CUDA detection
3. Model-pack manifest loading
4. Backend registration (token-protected)
5. Heartbeat every 10-30 seconds
6. Pull-based job polling
7. Pipeline execution
8. Stage updates
9. Artifact upload
10. Error reporting
11. Temporary file cleanup
12. Drain mode support
13. Update signaling placeholder

## 12. Local GPU Rendering Architecture

- Use local worker when `dispatch_preference=local`
- Use local worker when `dispatch_preference=auto` and local worker supports the job
- Do NOT use local worker if model pack is missing
- Do NOT use local worker if VRAM requirement is not met
- Do NOT use local worker if worker is stale, draining, or busy beyond policy
- If no compatible local worker: queue job, provision cloud worker if enabled, or fail gracefully

## 13. Remote Cloud Worker Architecture

### Provider Abstraction
- `backend/app/providers/base.py`
- `backend/app/providers/vastai.py`
- `backend/app/providers/runpod.py`

### Interface
```python
class CloudProvider:
    def list_available_gpus(self): ...
    def provision_worker(self, requirements): ...
    def terminate_worker(self, worker_id): ...
    def get_worker_status(self, worker_id): ...
```

### Cloud Provisioning Requirements
```json
{
  "min_vram_gb": 24,
  "preferred_gpu_classes": ["RTX 4090", "A10G", "A40", "A100", "L40S"],
  "model_pack": "model-pack-studio-cloud",
  "max_hourly_price": "configured",
  "idle_shutdown_minutes": 10
}
```

### Routing Rules
- Use cloud workers when `dispatch_preference=cloud_gpu`
- Use cloud workers when `dispatch_preference=auto` and no local worker is compatible
- Use cloud workers when job requires studio model pack unavailable locally
- Use cloud workers when estimated local runtime exceeds threshold

## 14. Model Architecture and Model Packs

### Model Packs
- `model-pack-lite`
- `model-pack-community-gpu`
- `model-pack-studio-cloud`
- `model-pack-commercial-safe`

The backend must remain model-agnostic. All generation models exposed through:
- Worker capabilities
- Model-pack manifests
- Model registry entries
- Exact model versions
- License statuses
- VRAM requirements

### Model Registry Entry Format
```json
{
  "model_id": "ace-step-1.5",
  "display_name": "ACE-Step 1.5",
  "engine": "acestep",
  "task": "song_generation",
  "version": "exact_version_here",
  "source_url": "model_or_repo_url",
  "license": "exact_license_here",
  "license_url": "license_url",
  "redistributable": "verified_or_needs_review",
  "commercial_safe": "verified_or_needs_review",
  "supports_vocals": true,
  "supports_instrumental": true,
  "supports_lyrics_conditioning": true,
  "supports_long_form": false,
  "min_vram_gb": 12,
  "recommended_vram_gb": 24,
  "default_container_policy": "bundled_or_mounted",
  "notes": "Exact license must be verified before official bundled release."
}
```

### Allowed License Statuses
- `verified`
- `needs_review`
- `not_allowed`
- `user_supplied_only`

Do NOT use vague statuses like "probably okay" or "open source maybe".

### Preferred Future Models
- ACE-Step / ACE-Step 1.5 (primary GPU song generation, subject to license verification)
- YuE (optional long-form lyrics-to-song for studio/cloud workers)
- Stable Audio Open (optional sample/loop/sound-design, subject to license)
- MusicGen (optional legacy/lightweight instrumental fallback)
- Demucs or equivalent (stem separation)
- Deterministic DSP tools (mastering first)

Official containers must NOT bundle model weights unless redistribution rights are verified.

### Scheduler Model Selection Flow
1. Read job request
2. Determine required capabilities
3. Check lyrics_mode
4. Check instrumental/vocal requirement
5. Check duration
6. Check quality
7. Check commercial-safe requirement if enabled
8. Query registered workers
9. Pick compatible worker with best capability/availability
10. If none exists and cloud enabled, provision worker
11. If no compatible worker, fail gracefully with clear reason

## 15. Storage and Retention Rules

### Storage Interface
```python
class StorageProvider:
    def upload_file(self, local_path, remote_key, metadata): ...
    def download_file(self, remote_key, local_path): ...
    def generate_signed_download_url(self, remote_key, expires_in): ...
    def delete_file(self, remote_key): ...
    def file_exists(self, remote_key): ...
```

### Retention Classes
- `temp_worker_file`: delete immediately after upload
- `failed_intermediate`: 24 hours
- `completed_job_assets`: 7 days (default)
- `debug_logs`: 7 days
- `commercial_extended`: future configurable option

### Object Layout
```
/jobs/{job_id}/input/request.json
/jobs/{job_id}/lyrics/lyrics_final.txt
/jobs/{job_id}/lyrics/lyrics_quality_report.json
/jobs/{job_id}/audio/draft.wav
/jobs/{job_id}/audio/final_master.wav
/jobs/{job_id}/exports/final.zip
/jobs/{job_id}/logs/pipeline.log
/jobs/{job_id}/metadata/job_manifest.json
```

### Storage Rules
- Generated files are private by default
- No public directory browsing
- Signed/download-controlled access required
- Default retention: 7 days
- Adapters: local, minio, s3_compatible
- Future targets: Amazon S3, Cloudflare R2, Backblaze B2, Wasabi, Google Cloud Storage, Azure Blob Storage

## 16. Cloud Compute Provider Rules

- Initial targets: Vast.AI, RunPod
- Provider logic abstracted; not hardcoded into job stages
- Real API calls may be placeholders in first scaffold
- Do NOT perform billing-sensitive provisioning unless explicitly enabled and configured
- API keys loaded from environment only; never committed

## 17. Test Frontend Requirements

- Framework: React/Vite
- Pages: `/setup`, `/login`, `/dashboard`, `/jobs/new`, `/jobs/{job_id}`, `/workers`, `/system`, `/settings`
- After job submission, frontend MUST redirect to `/jobs/{job_id}` (do NOT leave user on form)
- Job progress page shows: job ID, overall status, current stage, stage-by-stage progress, assigned worker, queue position, elapsed time, logs, artifacts, download button, failure reason, retry button, cancel button
- Polling via `GET /api/jobs/{job_id}` and `GET /api/jobs/{job_id}/logs`

## 18. Job Progress Page Requirements

Route: `/jobs/{job_id}`

Must show:
- Job title or label
- Job ID
- Overall status
- Current stage
- Stage-by-stage progress
- Assigned worker
- Worker status
- Queue position if available
- Elapsed time
- Logs
- Generated artifacts
- Download button when complete
- Failure reason if failed
- Retry button placeholder
- Cancel button

## 19. Community Edition vs Commercial Edition Boundaries

### Community Edition (Free)
- Full pipeline orchestration
- CPU test generation
- Local GPU generation (user-provided models)
- Worker-lite and worker-gpu-base
- Model packs with verified redistributable models
- Local and self-hosted storage
- Standard retention (7 days)

### Commercial Edition (Future, Paid)
- Extended retention options
- Cloud GPU provisioning management
- Studio model packs with verified commercial licenses
- Advanced mastering presets
- Priority queue processing
- Multi-user/team management
- API access
- Extended analytics

## 20. Development Logging Requirement

- Backend structured logs required
- Worker structured logs required
- Per-job pipeline logs required (included in ZIP as `/logs/pipeline_log.txt`)
- `DEVELOPMENT_LOG.md` must be updated for every meaningful development task
- A task is NOT complete until `DEVELOPMENT_LOG.md` has been updated
- Log format defined in `AGENTS.md`

## 21. AI Agent Rules

1. Read `OPENAUDIOLAB_MASTER_PLAN.md` before making changes
2. Follow current backend-first build priority
3. Preserve modular job pipeline
4. Preserve remote worker support
5. Preserve cloud GPU worker support
6. Preserve storage abstraction
7. Preserve default 7-day file retention
8. Preserve model-pack abstraction
9. Preserve lyric reasoning for AI-generated lyrics
10. Preserve custom lyric pass-through behavior
11. Do NOT build polished final UI before backend orchestration works
12. Do NOT hardcode a single model as the entire platform
13. Do NOT assume local GPU availability
14. Do NOT store generated files permanently
15. Do NOT remove queue, worker, storage, security, or model-pack abstractions
16. Do NOT ship unsafe default production credentials
17. Append task entry to `DEVELOPMENT_LOG.md` before considering task complete

## 22. Required Repository Structure

```
openaudiolab/
  OPENAUDIOLAB_MASTER_PLAN.md
  AGENTS.md
  DEVELOPMENT_LOG.md
  openaudiolab.manifest.json
  README.md
  docker-compose.yml
  .env.example
  .gitignore

  backend/
    app/
      main.py
      core/
      api/
      db/
      auth/
      setup/
      jobs/
      workers/
      storage/
      providers/
      models/
      lyrics/
      audio/
      exports/
      cleanup/
    tests/
    requirements.txt
    Dockerfile

  worker/
    worker_app/
      stages/
      audio/
      storage/
      update/
    model-packs/
    requirements.txt
    Dockerfile.lite
    Dockerfile.full

  frontend/
    package.json
    src/

  shared/
    schemas/
    constants/

  infra/
    docker/
    postgres/
    redis/
    minio/

  docs/
```

## 23. Immediate MVP Target

A user can:
1. Complete secure first-run setup
2. Log in
3. Open the test frontend
4. Submit a music generation job
5. Get redirected to a job progress page
6. Watch the job move through pipeline stages
7. Have a worker process the job
8. Store generated artifacts through a configurable storage backend
9. Download a final ZIP package
10. Generated files expire automatically after the configured retention period

---

**This document is the authoritative reference for all OpenAudiolab development decisions.**
