# OpenAudiolab Architecture

## Overview

OpenAudiolab is a music creation platform with a backend-first architecture. It consists of:

- **Backend API** (FastAPI/Python): Job orchestration, auth, setup, storage abstraction
- **Worker Runtime** (Python): Pipeline execution, GPU/CPU processing, artifact generation
- **Frontend** (React/Vite): Test UI for job submission and progress tracking
- **Infrastructure** (Docker Compose): PostgreSQL, Redis, MinIO

## Key Design Decisions

1. **Model-agnostic backend**: No single model hardcoded; all models exposed through worker capabilities and model-pack manifests
2. **Unified worker protocol**: Local GPU and remote cloud GPU workers use the same registration, heartbeat, and job polling protocol
3. **Storage abstraction**: Adapter-based storage (local, MinIO, S3-compatible) with configurable retention
4. **Secure first-run setup**: No default production credentials; setup required before public usage
5. **Custom lyrics preservation**: User-provided lyrics are never modified automatically

## Data Flow

```
User → Frontend → Backend API → Redis Queue → Worker → Storage → Frontend (polling)
```

## See Also

- [Pipeline Documentation](pipeline.md)
- [Worker Protocol](worker-protocol.md)
- [Storage Documentation](storage.md)
- [Model Packs](model-packs.md)
- [Cloud Providers](cloud-providers.md)
- [Security](security.md)
