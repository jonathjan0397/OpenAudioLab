# Milestone 1 — Contract-first API and identity

Status: **complete** on branch `impl/milestone-1` (commits `0fad838`, `69ae50d`).
Not merged to `master`; not deployed. Date: 2026-10-15.

## Scope delivered

- FastAPI application factory listening on port **50555** under `/api/v1`.
- Canonical error envelope and `X-Request-ID` correlation on every response.
- Exact-origin CORS allowlist (scheme + port), exposing `Location`,
  `Retry-After`, `X-Request-ID`.
- Model discovery from a static registry stub: ACE-Step 1.5 enabled; HeartMuLa,
  MiniMax Music 3, DiffRhythm 2 and YuE v1 present but disabled (never queued as
  ready — 503).
- Job admission `POST /jobs` returning 202 + `Location`, with strict discriminated
  validation and a required `Idempotency-Key`.
- Owner-scoped job list (cursor-paginated), detail, idempotent cancel, retry
  (new attempt number), artifacts stub, SSE resync stub, download-url stub.
- Durable `jobs` and `idempotency_records` tables via Alembic migration `0001`.
- Docker `core`/`storage`/`test` Compose profiles and a non-root API image with
  no GPU/model dependencies.
- GitHub Actions CI (pytest on Python 3.12).

## Identity decision (deviation from plan)

The owner directed that the backend does not authenticate users; it only handles
jobs handed to it by the trusted frontend. The contract's `Authorization: Bearer
<token>` shape is kept, but the token is treated as opaque and hashed into an
internal owner id used only for resource isolation. The plan's issuer/audience/JWKS
gate is therefore deferred to a later identity decision, not failed.

## Acceptance gates

| Gate (docs/IMPLEMENTATION_PLAN.md) | Result | Evidence |
| --- | --- | --- |
| Owner A cannot enumerate/read/cancel/retry/download owner B's jobs | Pass | `tests/test_ownership.py` (404 on every cross-owner route) |
| Issuer/audience checks fail correctly | Deferred | Superseded by trusted-frontend decision; opaque bearer only |
| Browser preflight works only for permitted origins | Pass | `tests/test_cors_and_openapi.py` (allow vs deny) |
| JSON round-trip preserves lyric whitespace/newlines/Unicode | Pass | `tests/test_jobs_submit.py::test_lyrics_preserved_verbatim_and_hashed` |
| Duplicate keys are safe under concurrent submits | Pass | `tests/test_idempotency.py::test_concurrent_duplicate_submit_creates_one_job` |
| Changed payload returns 409 | Pass | `tests/test_idempotency.py::test_same_key_different_payload_conflicts` |
| Unknown controls return 422 | Pass | `tests/test_jobs_submit.py::test_unknown_control_returns_422` |

## Validation run

- `pytest tests -q` → 44 passed.
- Live smoke on 50555: `/health/ready`, `POST /jobs` (202), `GET /models` — SQLite.
- Compose `core` against PostgreSQL 16: submit 202, idempotent replay 202,
  cross-owner 404, API container healthy.

## Known limits / deferred

- Model revisions are registry stubs until milestone-3 pinning.
- SSE is a single resync event; polling is the milestone-1 fallback per contract.
- Queue library, outbox and dispatcher arrive in milestone 2.
- `POST /artifacts/{id}/download-url` returns 404 until assets exist (milestone 2).
