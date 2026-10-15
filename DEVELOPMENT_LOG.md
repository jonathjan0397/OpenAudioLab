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
