# Milestones and acceptance gates

## 0 — Establish deployment facts and baseline

Inspect target server, existing frontend identity scheme, hostname/origin/TLS, persistent storage path, GPU inventory/topology, and whether inference is local or remote. Record findings and uncertainties. Confirm engine order: ACE-Step 1.5 first by default, MiniMax optional with conditional license review. User has not selected a GPU, provider budget, or deployment host. Do not provision or spend.

Select pinned Python/dependencies and queue library after checking official docs. Implement settings, repository layout, secret-free environment template, CI, and database migrations. Select application source license only with owner direction. Historical scaffold is abandoned. Build cleanly from the current root-level plan; any selective historical-code reuse requires a documented reason and correctness/licensing review.

## 1 — Contract-first API and identity

Build FastAPI on 50555, auth integration, exact CORS, request limits, OpenAPI, model discovery, health endpoints, owner-bound job CRUD, and canonical lyric hashing. Add strict request validation and idempotency. No inference or browser LLM calls in API.

Gate: owner A cannot enumerate/read/cancel/retry/download owner B's jobs; issuer/audience checks fail correctly; browser preflight works only for permitted origins; JSON round-trip preserves lyric whitespace/newlines/Unicode; duplicate keys are safe under concurrent submits; changed payload returns 409; unknown controls return 422.

## 2 — Durable orchestration and test worker

Implement PostgreSQL jobs/attempts/outbox/events/assets, Redis delivery, fenced leases, heartbeat/recovery, bounded retries, cancellation, artifact upload/finalization and seven-day cleanup. Use an opt-in deterministic WAV fixture worker so the pipeline can run without GPUs. Fixture artifacts must always be labeled synthetic test audio and must not appear as genuine engine output.

Gate: kill API/broker/worker at each dispatch boundary and prove persisted state recovers; duplicate delivery does not publish twice; stale lease callbacks fail; cancellation beats late completion; interrupted jobs reach a documented outcome; cross-owner asset paths fail; corrupted/oversized uploads are rejected; expiry invalidates downloads and deletes objects. Use migrations, not create_all as production upgrade strategy.

## 3 — First real music engine

Implement ACE-Step 1.5 using official version-pinned upstream interfaces behind an isolated worker. Verify complete runtime licenses, load health, model revisions, input limits, supported controls, native audio and topology. Do not invent API compatibility. If the target hardware only supports MiniMax or the owner prioritizes it, document that change before switching engine order.

Gate: a real vocal song from supplied lyrics and, if supported, a real instrumental are generated, decoded, persisted and delivered through the public API. Save benchmark evidence, native output metadata and input lyric hash. Verify cold-start readiness, out-of-memory handling, timeout behavior and worker drain. Mark this gate blocked if real GPU hardware is unavailable; passing mock tests cannot complete it.

## 4 — Frontend integration

Provide a small framework-independent integration example or generated TypeScript client, not a redesigned website. Demonstrate model discovery, final-lyric submit, polling/SSE, cancel, retry, playback and downloads. Keep the existing frontend LLM connection independent and secrets server-side. Polling works first; SSE adds authenticated reconnect and event replay without URL tokens.

Gate: an actual frontend integration against the configured HTTPS origin on port 50555/proxy succeeds; finished lyrics still submit when its LLM provider is offline; no long-lived service key enters browser bundles; expiring preview links refresh properly; required model notices are visibly rendered.

## 5 — Optional engines and operational readiness

Add HeartMuLa, DiffRhythm 2, YuE v1 or MiniMax only through the same adapter contract. Enable MiniMax only after its attribution/policy/authorization requirements are recorded. Pin each complete pipeline and benchmark it independently. Preserve local/remote worker compatibility. Add metrics, tested backups, retention schedules, production startup checks and deployment runbook.

Gate: capability-aware routing, atomic multi-GPU allocation and license gating are tested; unavailable engines fail clearly without substitution; restore/recovery is demonstrated; dependency scans and configuration review pass. Any cloud autoscaling needs separately configured spending caps and user authorization.

## Completion report required from coding agent

For each milestone list: changed files, commands run and results, actual engine/revision and hardware used, remaining stubs, migrations, environment settings, frontend changes required, known limits and next task. Never claim production-ready or deployed from scaffold-only or synthetic evidence.
