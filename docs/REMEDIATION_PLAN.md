# OpenAudioLab Remediation & Optimization Plan

Date: 2026-10-21. Mode: evidence-based planning, approved for incremental implementation.
Base: `feat/uais-artist-voice` @ `bfc1598` (UAIS deployed to hub as `uais-bfc1598`, unmerged to `master` @ `ea54f23`).
This is an improvement project on the existing FastAPI/Postgres/Redis/Docker architecture — no rewrite,
no Kubernetes, no new queue technology unless justified (§B, item Q1).

## A. Current-state architecture

API (50555, FastAPI) accepts jobs → durable `jobs` row + `idempotency` + credit debit + `outbox` row in one
transaction (`app/routes/jobs.py:646-670`) → separate dispatcher process LPUSHes queue keys and runs the
reconciler (`app/dispatcher.py`, `app/orchestration.py:95-171`). Workers (engine/training/audio) BRPOP their
queues, claim via `SELECT … FOR UPDATE` with attempt-uniqueness + lease token, heartbeat, and finalize with
lease-fenced conditional updates (`app/orchestration.py:183-251`). ACE-Step runs as a co-located HTTP engine
subprocess per worker node; model checkpoint is switched only when the target model differs
(`app/engine_worker.py:86-116`). Vast.ai burst + baseline-fallback + two training pools are managed by
`scripts/autoscale.py` (queue-depth driven). Frontend: React + React Query + Router, custom CSS, 4 themes,
canonical serializer `frontend/src/lib/generation.ts`. UAIS voice pipeline (`app/uais/`, `app/routes/voice.py`)
is live on the branch.

## B. Deficiency matrix

| ID | Sev | Issue | Evidence | Existing mitigation | Remaining deficiency | Correction | Deps | Risk | Acceptance |
|----|-----|-------|----------|--------------------|----------------------|-----------|------|------|-----------|
| R1 | P0 | Engine/timeout failures terminal; no transient/permanent classification, no backoff, no `next_retry_at` | `orchestration.py:471-490`; no `next_retry` in `app/` | Lease-expiry interruption requeues with `max_attempts=3` | Transient infra failures need manual retry | Error-classification table; transient/resource → bounded retry with exponential backoff + jitter via `jobs.next_retry_at` | migration 0034 | Med (retry loops) | Fault tests 17/18: repeated retryable failure stops at budget; permanent fails once |
| R2 | P0 | Lost BRPOP message strands a `queued` job forever | `orchestration.py:95-171` scans only running attempts; `maintenance.py` only expires assets | Outbox covers pre-publish loss | Post-publish message loss unrecoverable | Stranded-queued sweeper in reconciler re-publishes (idempotent) | none | Low | Crash between BRPOP and claim ⇒ job re-published and completes |
| R3 | P0 | Upstream ACE-Step `task_id` not persisted at submit | `engine_acestep.py:200-208`; `models.py:81-96` | task_id recorded in manifest on success | Worker death after submit ⇒ duplicate inference | Persist `job_attempts.upstream_task_id`; repoll before resubmit when the same engine still knows the task | migration 0034 | Med | Crash after submit ⇒ output recovered, no second paid inference |
| R4 | P0 | Failed generations never refund user credits | `jobs.py:646-663` up-front debit; refunds exist only for voice jobs | Guest reservation released on fail | User keeps paying for terminal failures | Idempotent refund `CreditEntry` on terminal failure (`gen-refund:{job}`); explicit retry re-charges | R1 | Med (double-refund) | Terminal failure ⇒ balance restored exactly once; retry re-debits |
| R5 | P1 | Unhealthy worker keeps claiming during cooldown | `engine_worker.py:245-258,450-466` | `unhealthy_until` consumed only by autoscaler | OOM'd worker re-claims and re-OOMs | Honor `unhealthy_until` at claim (defer, don't burn attempt) | none | Low | Cooldown window shows no new claims |
| R6 | P1 | Audio worker has no heartbeat thread (900 s demucs vs 30 s lease) | `audio_worker.py:263`; `config.py:134` | beats between outputs | False interruption + duplicate export | Attempt heartbeat thread (engine-worker pattern) | none | Low | Long separation completes without interruption |
| R7 | P1 | Engine escalation coarse: no hang/timeout restart policy | `engine_worker.py:567-575,696-701` | start-failure restart + unhealthy | Hung engine stalls later jobs | Escalation: timeout/OOM ⇒ engine restart + cooldown before next claim | R5 | Med | After ENGINE_TIMEOUT the engine subprocess is recycled |
| R8 | P1 | Core compose: dispatcher/workers inherit API-port healthcheck (always "unhealthy"); no restart policies; mutable tags | `docker-compose.yml:81-194`; `Dockerfile:35-36` | backend stack disables healthcheck correctly | Wrong health signals; dev stack dies on crash | Disable/replace healthchecks per service; `restart: unless-stopped`; pin mutable tags (`minio:latest`, `:dev` default) | none | Low | `docker ps` shows honest health; containers self-restart |
| R9 | P1 | Autoscaler: burst dph cap defaults 0 (uncapped); state in `/tmp`; no mid-job drain check | `autoscale.py:54,106,829-832` | train-xl dph cap; burst-drain guard | Unbounded spend possible; reboot orphans nodes | Default `OAL_MAX_DPH=0.40`; state path env-overridable default `/var/tmp`; hold scale-down while burst workers run attempts | none | Low | Burst node never stopped with a running attempt; state survives `/tmp` cleanup |
| R10 | P2 | Studio stats capped at 50-row page; credit % hardcoded /5000 | `Studio.tsx:143,441,464,467` | — | Wrong lifetime totals; wrong denominator | Aggregate stats endpoint + plan `monthly_credits` allowance (`routes/billing.py:19-22`) | none | Low | Totals match DB counts; denominator = plan allowance |
| R11 | P2 | Nav active-state bugs + duplicate destinations + no mobile menu | `Studio.tsx:434,78-80`; `styles.css:555` | header nav correct with `end` | Misleading highlight; hidden destinations | NavLink-based active states, dedupe Dashboard/My Tracks, responsive menu | none | Low | Exactly one active item per route; no horizontal scroll at 375 px |
| R12 | P2 | Fabricated queued progress (8%/6%); raw stage strings; no Retry button; reload loses job context | `CreateWidget.tsx:843`; `Studio.tsx:910` | StatusPill humanizes status | Invents percentages; recovery invisible | Indeterminate bar when `progress==null`; stage-label map; Retry button; persist active job id | none | Low | No invented numbers; failed job retryable in-widget; reload keeps tracker |
| R13 | P2 | A11y: ~14 aria hits, no `:focus-visible`, no reduced-motion, sub-44 px targets | `styles.css` grep; `App.tsx:86` | radiogroup model cards | WCAG gaps | focus-visible + reduced-motion CSS; bell → button; label tap targets | none | Low | Keyboard-only flow works; visible focus everywhere |
| R14 | P3 | No profile-aware claim: turbo-only worker pops premium jobs (requeue-loop); per-claim free-VRAM unchecked; `GpuLease` dead | `engine_worker.py:567-575`; `models.py:797-809` | capability gating at API; ENGINE_BUSY requeue | Wasted hops on mixed fleet | Benchmark first, then claim-time capability check or per-profile queue | R7 | Med | Baselines recorded; premium hop-rate measured before tuning |
| R15 | P3 | Scaling by queue depth only; no time estimates | `autoscale.py:708-726` | tiered scale-down | Over/under-provisioning | Workload-aware estimate (duration × model class) after benchmarks | R14 | Med | Provision decisions justified by recorded baselines |
| R16 | P4 | Creator: quote shown post-submit; per-keystroke draft writes; no multi-tab sync | `CreateWidget.tsx:189-214,661` | server quote bound pre-submit | No pre-submit price preview; IO churn | Pre-submit quote display; debounced draft + `storage` event | none | Low | Price visible before Generate; ≤1 write/second while typing |
| R17 | P4 | Studio library: no search/sort/pagination; ~10 buttons/row; monolithic pages | `Studio.tsx:516-637` (930 ln); Admin 1983 ln | workspace chips, filters | Doesn't scale to 1000s tracks | Search/sort/pagination + overflow menu; component extraction | R10 | Med | 500-track library usable; rows ≤3 primary actions + menu |
| R18 | P4 | Mobile: no hamburger; player bar cramped <560 px | `styles.css:263-276,555` | track-row reflow | Nav discoverability | Intentional responsive menu + player compaction | R11 | Low | 320–1920 px audit clean |
| R19 | P5 | Artist UX: no name/bio edit; consent checkbox decorative; Voice Studio separate from Artist workspace | `Artist.tsx:191-192`; `VoiceStudio.tsx:76,143` | UAIS API complete | Fragmented journey | Artist workspace sections (Overview/Music/Voice/Settings); consent gating | none | Low | Artist Creator workflow (§22) end-to-end in UI |
| R20 | P5 | Widget shows no per-model voice state | `CreateWidget.tsx:162-168` | compat matrix in Voice Studio | Users discover incompatibility at submit | Show bound-artist state pill from compatibility data | R12 | Low | State visible before submit |
| R21 | P6 | Fault-injection gaps: stranded re-publish, ENGINE_TIMEOUT, OOM, eviction, cancel-during-recovery, training resume | audit §3; `MILESTONE_5.md:96` | 285 tests, strong fencing coverage | Unverified recovery paths | Add fault tests per §24 subset; training resume later | R1-R9 | Low | Named scenarios each have a test |
| Q1 | — | Redis Streams migration? | `queue.py`, outbox design | Lists + outbox + fencing work | — | **No migration.** Lists + reconciler sweeper (R2) closes the durability gap; Streams adds consumer-group complexity without new guarantees here | R2 | — | Decision recorded |

## C. Worker recovery architecture

Error classification (single table in `app/orchestration.py`):
- **TRANSIENT** (retry, bounded): `ENGINE_UNAVAILABLE`, `ENGINE_TIMEOUT`, HTTP/connection errors, storage
  interruption, `ENGINE_BUSY` (already requeues without burning budget).
- **RESOURCE** (retry elsewhere + quarantine worker): `ENGINE_OOM`, `ENGINE_START_FAILED`, model-load failure.
- **PERMANENT** (terminal): validation/4xx, missing assets, ownership, `VOICE_*` incompatibilities,
  `MAX_ATTEMPTS`, bad artifact.

Retry policy: attempt budget `max_attempts` (3) unchanged; transient/resource requeue sets
`next_retry_at = now + min(60, 5·2^(attempt-1)) + jitter(0–2 s)`; dispatcher skips unpublished outbox rows
whose job is not yet eligible. Every retry already records job/attempt/worker/lease via `JobAttempt` + events.
Worker states (documented subset of §6 mapped onto existing fields): `READY` (registered, heartbeat fresh),
`BUSY` (running attempt), `DRAINING` (`workers.drain`), `UNHEALTHY` (`unhealthy_until` future — now honored
at claim), `OFFLINE` (heartbeat stale). Escalation L1 retry → L2 engine HTTP reset → L3 engine subprocess
restart + cooldown → L4 container restart (`unless-stopped`) → L5 quarantine (cooldown) → L6 autoscaler
replacement → L7 admin alert (`errorlog`). Circuit breaker: repeated OOM on same worker extends cooldown.

## D. GPU performance plan

Keep per-job cached checkpoint switching (verified correct). Before scheduling changes, record baselines:
cold model load, warm generation by model, checkpoint transition latency, queue wait, peak VRAM (existing
`nvidia-smi` telemetry). Then: claim-time capability check (worker skips jobs it cannot run without burning
attempt budget — requeue like `ENGINE_BUSY`), optional per-profile queue split if hop-rate justifies it,
per-claim free-VRAM check for premium. Training already isolated on its own queues/pools. Tradeoff: skip-and-
requeue costs a hop but preserves fairness; no batching changes until measured.

## E. UI/UX improvement plan

Navigation: single active state (NavLink `end`), dedupe Studio sidebar (Overview / My Music / Workspaces /
Activity), responsive menu replacing invisible scroll. Song Creator: Simple mode keeps idea, artist state
pill, quality, duration, vocal/instrumental, assistant, Generate + server quote; engine internals stay in
the collapsible technical section. Studio: aggregate stats endpoint, allowance-based credit display, library
search/sort/pagination with overflow menu. Progress UX: honest indeterminate states, stage-label map,
recovery/retry visibility, persisted job tracker. Artist workspace integrates Voice Studio. Mobile: 320–1920
audit, player compaction, ≥44 px primary targets.

## F. Component change map

Modify: `app/orchestration.py` (classification, retry, sweeper, refund), `app/engine_worker.py` (task_id
persist/repoll, claim quarantine, escalation), `app/audio_worker.py` (heartbeat thread), `app/dispatcher.py`
(eligibility), `app/routes/jobs.py` (retry re-charge, stats), `scripts/autoscale.py` (caps, state path,
drain hold), `docker-compose.yml`, `frontend/src/pages/Studio.tsx` (fix + extract),
`frontend/src/components/CreateWidget.tsx` (quote, draft, pill, retry), `frontend/src/styles.css`
(focus/motion/menu), `frontend/src/App.tsx` (nav). Extract (new files): `frontend/src/components/JobTracker.tsx`,
`frontend/src/components/TrackLibrary.tsx` (Phase 4), `frontend/src/pages/ArtistWorkspace.tsx` (Phase 6).
Unchanged: serializer semantics, outbox design, UAIS core, PlayerContext, themes.

## G. Database & API migration plan

Migration `0034_recovery`: `jobs.next_retry_at` (nullable timestamptz), `job_attempts.upstream_task_id`
(nullable string). Additive only; no data rewrite; rollback = drop columns (old code ignores them).
API additions: `GET /api/v1/tracks/stats` (total/shared/favorites counts), `me`/billing response gains
`monthly_credits` allowance; job detail gains `next_retry_at` + retry-count fields. Backward compatible.

## H. Testing matrix

Unit: classification table, backoff bounds, refund idempotency. Integration: stranded sweeper re-publish;
transient retry reaches success; MAX_ATTEMPTS terminal + refund; task_id repoll recovery (fake engine).
Fault-injection (§24 subset now): crash before claim (R2), after claim (exists), after submit (R3), engine
hang/timeout restart (R7), OOM quarantine (R5), cancel-during-recovery. Browser: nav active-state, creator
quote-before-submit, mobile 375 px smoke. A11y: focus-visible, reduced-motion, keyboard submit flow.
Performance: recorded baselines (D), not invented targets.

## I. Prioritized roadmap

- **Phase 1 (P0)** — R1–R4 + migration 0034. Gate: fault tests 1–5, 17, 18 pass; no double-billing.
- **Phase 2 (P1)** — R5–R9. Gate: fault tests 6–13, 19, 20; honest container health.
- **Phase 3 (P2)** — R10–R13 (+R20 data where cheap). Gate: no fabricated numbers; credits match billing;
  keyboard-only create flow works.
- **Phase 4 (P3)** — R14–R15 after benchmarks. Gate: baselines recorded; hop-rate improved.
- **Phase 5 (P4)** — R16–R18. Gate: 320–1920 px clean; library usable at 500 tracks.
- **Phase 6 (P5)** — R19–R20. Gate: Artist Creator workflow (§22) in UI.
- **Phase 7 (P6)** — R21 + E2E workflows + deployment/rollback rehearsal + XL real-GPU benchmark.

## J. Implementation handoff

First milestone = Phases 1–3 on `feat/uais-artist-voice`, phase-sized commits, tests with each phase,
full suite + frontend build green before review. No production config changes without rollout/rollback note
(compose healthchecks/restarts ship with the Phase 2 deploy). No paid cloud spend during implementation.
