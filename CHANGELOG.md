# Changelog

All notable changes to the OpenAudioLab backend implementation. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Implementation lives on
feature branches; `master` remains the documentation/planning baseline until the
owner approves a merge. Per-milestone acceptance records are in `docs/MILESTONE_N.md`.

## [Unreleased]

### Added
- Milestone 2 (in progress): durable orchestration — attempts, events, outbox,
  assets, workers; Redis delivery; dispatcher; deterministic WAV fixture worker;
  private artifact storage with expiring download URLs and seven-day cleanup.

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
