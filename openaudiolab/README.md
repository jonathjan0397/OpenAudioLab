# OpenAudiolab.io

Open-source music creation platform with a free Community Edition and a future paid Commercial Edition.

**Current Version:** 0.1.0-foundation  
**Status:** Active development — backend foundation and job orchestration scaffold

---

## What Is OpenAudiolab?

OpenAudiolab is an open-source platform for AI-assisted music creation. It supports:

- AI lyric generation with reasoning and humanization
- Custom lyric pass-through (preserves user lyrics exactly)
- Composition planning
- Music/audio generation (local GPU or remote cloud GPU)
- DAW-style audio processing, effects, and mastering
- Preview and waveform generation
- Final downloadable ZIP export
- Short-lived generated file storage with configurable retention
- Local GPU generation and remote cloud GPU workers (Vast.AI, RunPod)

## Current Development Status

This is the **initial foundation scaffold** (v0.1.0-foundation). It establishes:

- Backend job orchestration with real state machine
- Worker container architecture (local + remote)
- Secure first-run setup
- Storage abstraction with retention
- CPU-safe test generation
- ZIP export pipeline
- Simple test frontend with job progress page
- Development logging discipline

**Real AI music generation is NOT fully implemented yet.** The current scaffold uses CPU-safe test audio generation (synthetic tones/chords) to validate the full pipeline. Real model integration comes after pipeline orchestration is proven.

## Architecture Summary

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Frontend   │────▶│   Backend   │────▶│   Worker    │
│ React/Vite  │     │   FastAPI   │     │  Container  │
└─────────────┘     └──────┬──────┘     └──────┬──────┘
                           │                   │
              ┌────────────┼────────────┐       │
              ▼            ▼            ▼       ▼
         PostgreSQL     Redis       MinIO/S3  GPU/CPU
```

- **Backend:** FastAPI (Python) with PostgreSQL, Redis queue, and storage abstraction
- **Worker:** Unified container runtime for local GPU and remote cloud GPU workers
- **Frontend:** React/Vite test frontend for job submission and progress tracking
- **Storage:** Adapter-based (local, MinIO, S3-compatible) with configurable retention
- **Cloud Providers:** Vast.AI and RunPod (abstraction layer; real API calls are placeholders)

## Runtime Modes

### No-GPU Backend Mode
The system runs on servers without GPUs. Backend, database, Redis, storage, frontend, job creation, and worker registration all work. CPU-only 15-second test generation validates the pipeline. The UI shows: "Local generation unavailable. No compatible GPU with required VRAM was detected."

### Local GPU Mode
Available when an NVIDIA GPU with CUDA and minimum 12 GB VRAM is detected, the required model pack is installed, and the worker is registered.

### Remote Cloud GPU Worker Mode
Remote workers use the same protocol as local workers. Provider targets: Vast.AI and RunPod. Requires explicit configuration and enablement.

## Security / First-Run Setup

The system is secure at first install:

- No default production credentials shipped
- First-run setup creates initial admin account
- Passwords hashed with bcrypt; never stored plaintext
- Worker registration requires `WORKER_REGISTRATION_TOKEN`
- Generated files are private by default; signed downloads required
- Default 7-day file retention
- No real secrets committed to the repository

## Quick Start (Docker Compose)

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)
- Node.js 18+ (for local frontend development)

### 1. Clone and Configure

```bash
cd openaudiolab
cp .env.example .env
# Edit .env with your settings (change default tokens!)
```

### 2. Start Services

```bash
docker compose up -d
```

This starts:
- Backend (FastAPI on port 8000)
- Frontend (React/Vite on port 5173)
- PostgreSQL
- Redis
- MinIO (local storage)
- Worker-lite (CPU test worker)

### 3. Complete First-Run Setup

1. Open `http://localhost:5173` in your browser
2. You will be redirected to `/setup`
3. Create your initial admin account
4. Confirm storage settings
5. Generate a worker registration token

### 4. Log In and Submit a Test Job

1. Log in with your admin credentials
2. Navigate to "Create Test Job"
3. Fill in the job form (prompt, genre, mood, lyrics mode, etc.)
4. Submit the job
5. You will be redirected to the job progress page
6. Watch the job move through pipeline stages
7. Download the final ZIP when complete

## How to Submit a Test Job

1. Log in to the frontend
2. Go to `/jobs/new`
3. Fill in:
   - **Prompt:** Description of the song you want
   - **Genre:** e.g., "country rock", "electronic", "jazz"
   - **Mood:** e.g., "gritty, emotional, anthemic"
   - **Lyrics Mode:** `ai`, `provided`, `hybrid`, or `instrumental`
   - **Provided Lyrics:** (if `provided` or `hybrid` mode)
   - **Duration:** in seconds (default 90, max 15 for CPU test)
   - **Vocal Mode:** male, female, or both
   - **Quality:** draft, standard, high, or studio
   - **Dispatch Preference:** auto, local, remote_worker, cloud_gpu, or cpu_test
4. Click "Submit Job"
5. You will be redirected to `/jobs/{job_id}` to watch progress

## How to Run Worker-Lite

Worker-lite is included in the Docker Compose setup. It runs automatically and registers with the backend using the `WORKER_REGISTRATION_TOKEN`.

To run worker-lite standalone:

```bash
cd worker
docker build -f Dockerfile.lite -t openaudiolab-worker-lite .
docker run -e BACKEND_URL=http://host.docker.internal:8000 \
           -e WORKER_REGISTRATION_TOKEN=your-token \
           -e WORKER_NAME=local-test-worker \
           -e WORKER_MODE=lite \
           openaudiolab-worker-lite
```

## Where Generated Files Are Stored

- **Local storage:** `/data/openaudiolab/storage` (configurable via `LOCAL_STORAGE_PATH`)
- **MinIO:** `http://localhost:9000` (bucket: `openaudiolab-jobs`)
- **S3-compatible:** Configured via environment variables

Object layout:
```
/jobs/{job_id}/input/request.json
/jobs/{job_id}/lyrics/lyrics_final.txt
/jobs/{job_id}/audio/draft.wav
/jobs/{job_id}/audio/final_master.wav
/jobs/{job_id}/exports/final.zip
/jobs/{job_id}/logs/pipeline.log
/jobs/{job_id}/metadata/job_manifest.json
```

## Retention Policy

- **Default:** 7 days
- **Configurable:** via `DEFAULT_RETENTION_DAYS` environment variable
- **Retention classes:**
  - `temp_worker_file`: deleted immediately after upload
  - `failed_intermediate`: 24 hours
  - `completed_job_assets`: 7 days (default)
  - `debug_logs`: 7 days
  - `commercial_extended`: future configurable option

Generated files expire automatically after the configured retention period.

## Important Project Files

| File | Purpose |
|------|---------|
| `OPENAUDIOLAB_MASTER_PLAN.md` | Single source of truth for all development decisions |
| `AGENTS.md` | Mandatory instructions for all developers and AI agents |
| `DEVELOPMENT_LOG.md` | Append-only development history |
| `openaudiolab.manifest.json` | Project manifest with configuration and capabilities |
| `docker-compose.yml` | Local development orchestration |
| `.env.example` | Environment variable template |
| `backend/app/main.py` | FastAPI application entry point |
| `worker/worker_app/main.py` | Worker application entry point |
| `frontend/src/App.tsx` | React application entry point |

## Warning

**Real AI music generation is NOT fully implemented in this scaffold.** The current version uses CPU-safe test audio generation (synthetic tones/chords) to validate the full pipeline. Real model integration (ACE-Step, YuE, MusicGen, etc.) will be added in future versions after the pipeline orchestration is proven.

## License

OpenAudiolab is an open-source project. See individual model licenses in model-pack manifests for model-specific restrictions.
