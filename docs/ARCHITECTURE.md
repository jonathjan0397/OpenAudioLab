# Architecture decision: standalone music API

Planning baseline: 2026-10-15. Requirements are agreed in conversation; implementation choices below are proposed defaults for the coding agent to validate.

## Responsibility boundary

The frontend owns lyric brainstorming, generation, editing, reasoning, and its separate LLM configuration. Treat all lyrics arriving here as finalized external input regardless of whether a human or LLM wrote them. `lyrics_origin` is descriptive metadata and must never select a backend lyric-rewriting pipeline. Instrumental requests require no lyrics.

The backend owns authentication/authorization, model discovery, request validation, durable jobs, scheduling, progress, GPU execution coordination, artifact storage, retention, and audit metadata. It may translate music-control fields into an engine payload deterministically. It must not silently transform the lyric string. If an engine requires incompatible lyric formatting, return a validation error explaining the requirement.

## Services

| Component | Proposed implementation | Responsibility |
| --- | --- | --- |
| Public API | Python 3.12, FastAPI, Pydantic, Uvicorn | Versioned REST, auth, OpenAPI, polling and SSE |
| Database | PostgreSQL 16+, SQLAlchemy 2, Alembic | Users, jobs, attempts, outbox, events, assets, workers, registry |
| Broker | Redis with a validated queue library | At-least-once delivery, separate engine queues |
| Dispatcher/reconciler | Separate Python process | Publish outbox, claim work, reconcile leases and interruptions |
| GPU worker | Engine-specific isolated runtime | Model loading, inference, cancellation, result validation |
| Storage | Local adapter for development; private S3-compatible adapter for deployment | WAV originals, previews, checksums, manifests, expiry |
| Cleanup | Scheduled service | Expired asset deletion and temporary-file cleanup |

Choose and document the queue library in milestone 0. Implement this architecture cleanly; the old scaffold is abandoned. In particular, the old job API appears to authenticate callers without checking ownership in the route; verify all reused code instead of inheriting assumptions.

## Network and port

The API listener and container port default to **50555**, with a configurable bind address. Development may bind 127.0.0.1; containers bind 0.0.0.0. Compose maps 50555:50555. The external frontend uses a configured HTTPS API URL whose ingress can terminate TLS on 50555, or a standard HTTPS reverse proxy forwarding privately to 50555. Record the actual deployment mapping rather than treating port 50555 as TLS by itself. Never connect an HTTPS browser page to plain HTTP in production.

Postgres, Redis, object storage administration, and inference endpoints stay on private networks. CORS is an exact origin allowlist, including scheme and port. It is not authentication. Browser code receives per-user access tokens, never shared backend or provider secrets. Prefer short-lived JWTs from the configured identity provider, validated against fixed issuer/audience/JWKS settings. A same-origin frontend server may alternatively act as a BFF and retain credentials server-side. Confirm the existing website's identity scheme before implementing auth; do not invent a new user database unless necessary.

## Persistent data

- `jobs`: UUID, authenticated owner, canonical input, input hash, model revision, policy snapshot, status, created/updated/expires timestamps, selected worker, current attempt, cancellation timestamp.
- `job_attempts`: attempt UUID, parent job, attempt number, lease token, heartbeat, outcome, safe failure code, engine version, start/finish timestamps.
- `job_events`: monotonically ordered cursor per job, attempt ID, status/stage/progress/message and timestamp. Never include secrets or full lyrics in routine events.
- `outbox`: pending dispatch records inserted in the same transaction as jobs/attempts.
- `assets`: UUID, job/owner, opaque storage key, role, MIME, bytes, SHA-256, sample rate/channels/duration, expiry, deleted timestamp.
- `workers`: identity, authentication/key reference, supported exact model revisions, GPU topology/VRAM, heartbeat, drain state, capacity.
- `model_releases`: registry metadata, pinned revisions, independently verified code/weights/codec/dependency license evidence, capabilities, operational status.
- `idempotency_records`: owner, route, key, canonical request hash, response/job reference, expiry.

Use UTC timestamps. Database constraints enforce unique owner+route+idempotency key and one active lease per attempt. Ownership must be joined or checked for every access, including SSE, logs, cancellation, retry, and download URLs.

## Execution and failure semantics

Accept a valid job with HTTP 202 only after persisting job and outbox atomically. Dispatch at least once; worker claims and lease fencing make repeated messages harmless. A worker must hold the current attempt lease to upload or complete. Stale callbacks and late results cannot overwrite cancellation or newer attempts.

Public statuses: `queued`, `waiting_for_worker`, `running`, `cancelling`, `succeeded`, `failed`, `cancelled`. Asset expiration is separate (`assets_expired_at`), preserving historical generation outcomes. Worker loss marks the attempt interrupted after lease expiry; bounded policy may create a fresh attempt. Do not promise exactly-once GPU computation.

Queued cancellation is immediate. Running cancellation becomes `cancelling`; adapters report cooperative cancellation or the supervisor terminates an isolated local task when safe. Remote HTTP cancellation may only discard late results and may not stop upstream compute; return that distinction. Timeouts include model load, execution, heartbeat, upload, and total wall time.

GPU allocation is atomic. Start with one active inference task per compatible GPU allocation. A multi-GPU engine reserves all required devices together. No generic 12-GB assumption. API remains ready without GPUs; generation availability is advertised separately. Missing workers produce a bounded wait, with a configured deadline and clear failure reason. Cloud provisioning is disabled by default and cannot be a silent fallback.

## Artifacts and operations

Validate actual audio content and decodability, duration, channel count, byte limit, and checksum before publishing any result. Preserve native WAV as the original. Optional preview conversion is a separate task; label processing honestly. Never label copied audio as mastered or call identical copies stems.

Private bucket/key paths are server-generated; clients cannot submit filesystem paths or arbitrary provider URLs. Publish artifact metadata only after finalized upload. Use authenticated delivery or short-lived signed URLs and support HTTP Range playback. Avoid forwarding authorization to redirected, untrusted download origins. Default generated asset retention is seven days; bounded user overrides are role/policy controlled. Object deletion is idempotent and auditable.

Expose liveness, dependency readiness, worker availability, queue depth/age, GPU allocation, failure rates and inference latency. Use request/job/attempt IDs for correlation. Redact lyrics, tokens and signed URLs from routine logs. Production startup fails on unsafe secrets or invalid auth configuration. Bound request/upload sizes and per-user job concurrency. No live service is being deployed in this planning task.


## Capability specification v0.2 additions

`SERVICE_CATALOG.md`, `OUTPUT_SPEC.md` and `ARTIST_TRAINING.md` define the expanded service scope. This repository implements no frontend. Frontend integration gates mean API/client contract tests and documented coordination with the separate website, not building a website here.

Add separate worker queues/capabilities for generation, processing/rendering, separation/export, dataset preparation, fine-tuning and evaluation. Training jobs share the durable job/attempt/lease/event infrastructure but use separate GPU allocation and cost limits. Never allocate the same reserved devices concurrently across training and inference. Inference admissions and training admissions enforce distinct capacity policies.

Add database models for projects and immutable version graphs, artist profiles/versions, datasets/versions, training runs, evaluations, rights records, processing/session manifests, and transactional usage reservations/settlements. Resource authorization extends to every referenced input, not just the parent job. Public job success describes completed execution; training success does not mean evaluation passed or a candidate was activated.

Generation freezes model and profile versions. Dataset preparation freezes original asset references/checksums and produces an immutable prepared version; training freezes that dataset and base/recipe revisions. Candidate activation is a separate owner-authorized state change, with rollback. Profiles may carry separate musical-style and singer-identity components, applied only with supported compatible adapters.

Full mixes export as WAV and MP3. Native or separated stems export as aligned WAV and optionally ZIP. Preserve native originals and label processing. Store waveform peaks and analysis results for the frontend; do not render frontend controls. Store validated session/edit graphs and execute offline renders; responsive live playback stays in the frontend.

Retention is class-based: generated outputs retain the existing seven-day default unless deployment policy changes; active profile artifacts and required manifests remain while active; source training data follows explicit owner retention, not automatic output expiry; temporary preparation segments/checkpoints have bounded cleanup. Deletion revokes access first, then removes objects/caches under recorded policy. Saved song permanence has not been confirmed and is not implied by project metadata persistence.
