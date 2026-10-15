# Milestone 2 — Durable orchestration and test worker

Status: **complete** on branch `impl/milestone-1`. Not merged to `master`; not
deployed. Date: 2026-10-15.

## Scope delivered

- Durable tables via Alembic migration `0002`: `job_attempts`, `job_events`,
  `outbox_records`, `assets`, `workers`; `jobs` gains `stage`, `progress`,
  `progress_source`.
- **Queue mechanism decision** (milestone-0 item): plain Redis lists
  (LPUSH + BRPOP) with database-coordinated claims. At-least-once delivery;
  duplicate messages are harmless because claims are guarded by job state and
  attempt uniqueness. No queue-library dependency; remote Vast.ai workers will
  use the same primitive over TLS Redis. Redis is a delivery hint only — the
  database is the authoritative job truth.
- **Dispatcher** (separate process, `python -m app.dispatcher`): publishes the
  outbox (marking rows published so a restart cannot double-publish a committed
  row) and reconciles expired leases (interrupted attempt → requeue with a new
  attempt number, or `failed` with `MAX_ATTEMPTS` when the budget is exhausted,
  or `cancelled` when cancellation was requested).
- **Fixture worker** (opt-in `test` profile, `python -m app.worker`): claims a
  queued job with a fenced lease token, heartbeats, generates a deterministic
  mono 44.1 kHz WAV (frequency derived from the lyrics hash + seed), validates
  decodability/size, uploads to storage, and finalizes one asset. Every fixture
  artifact is labeled `synthetic_test_audio` and never presented as real engine
  output.
- **Lease fencing and completion guards**: a completion callback with a stale
  lease token is rejected (`stale`); a result that arrives after the job left
  `running` is `discarded` and cannot publish assets (cancellation beats late
  completion).
- **Private artifact storage**: local-filesystem adapter with server-generated
  keys (clients never submit paths). Assets carry role, MIME, byte count,
  SHA-256, sample rate/channels/duration, synthetic flag and a seven-day
  expiry.
- **Download URLs**: `POST /artifacts/{id}/download-url` returns a short-lived
  HMAC-signed URL (expiry capped by both the TTL and the asset retention);
  `GET /artifacts/{id}/content` serves bytes with HTTP Range (206) support and
  returns 410 once retention has expired.
- **Seven-day cleanup**: `python -m app.maintenance` deletes expired output
  objects and records deletion (idempotent).
- **API updates**: job detail reports real `stage`/`progress`/`progress_source`;
  artifacts list returns finalized asset metadata; SSE replays persisted events
  with `Last-Event-ID` and follows until a terminal state (polling remains the
  fallback).

## Acceptance gates

| Gate (docs/IMPLEMENTATION_PLAN.md) | Result | Evidence |
| --- | --- | --- |
| Persisted state recovers across API/broker/worker interruption | Pass | `test_interrupted_recovery_requeues`, `test_attempt_budget_exhausted` |
| Duplicate delivery does not publish twice | Pass | `test_dispatcher_publishes_once_no_double_publish`, `test_duplicate_delivery_does_not_run_twice` |
| Stale lease callbacks fail | Pass | `test_stale_lease_callback_fails` |
| Cancellation beats late completion | Pass | `test_cancel_beats_late_completion` (result discarded, no asset) |
| Interrupted jobs reach a documented outcome | Pass | requeue / `MAX_ATTEMPTS` / cancelled paths above |
| Cross-owner asset paths fail | Pass | `test_cross_owner_asset_paths` (404) |
| Corrupted/oversized uploads are rejected | Pass | `test_corrupt_artifact_fails` (`ARTIFACT_INVALID`) |
| Expiry invalidates downloads and deletes objects | Pass | `test_expiry_invalidates_download_and_deletes_object` (410 + object removed) |
| Migrations, not `create_all`, are the upgrade strategy | Pass | Alembic `0001`/`0002`; tests run `alembic upgrade head` |

## Validation run

- `pytest tests -q` → 58 passed (14 new orchestration tests).
- Compose `core` + `test` against PostgreSQL 16 + Redis 7: submit → dispatcher
  publish → fixture worker → `succeeded`; artifact listed as
  `synthetic_test_audio`; download URL served 200 (full) and 206 (Range);
  decoded WAV verified (mono, 44100 Hz, 132300 frames for a 3 s target).
- Fixed during validation: the shared `artifacts-data` volume must be writable
  by the non-root container user (Dockerfile now pre-creates it), and the
  worker logs swallowed exceptions instead of reporting them.

## Known limits / deferred

- The local-filesystem storage adapter is a single-host optimization; the
  S3-compatible adapter (durable across hosts) arrives with milestone 3/4.
- The fixture worker's heartbeat thread is adequate for short synthetic tasks;
  long GPU inference will need the same lease/heartbeat discipline in the real
  engine adapter.
- SSE follows for a bounded window then closes with a `resync` hint; authenticated
  reconnect/replay is in place, but no URL-token streaming is required yet.
- Worker registration/heartbeat is recorded but not yet exposed through the
  `/internal/v1` worker API (deferred to the real-engine milestone).
