# GPU Orchestration — Smart Queue, Swappiness, Fleet Console

Implements the Unified Smart GPU Orchestration specification (2026-10-21) on
`feat/gpu-orchestration`. One coordinated system on top of the existing
infrastructure — no second scheduler, no rewrite.

## Components

### A. Smart Model Queue Manager (SMQM) — `app/engine_worker.py`

All model families share one Redis list (`oal:queue:ace-step-1.5` + `:burst`);
the model lives in `job._admission`. SMQM makes selection **logical-model-aware**:

- **Peek window** (`scheduler_peek_window`, default 20): LRANGE of the list tail
  (the items BRPOP would consume next), one DB eligibility query
  (status `queued`, retry backoff elapsed, worker capability via
  `_can_run_profile`), then selection:
  - jobs matching the **loaded checkpoint** are preferred (FIFO within group);
  - when the loaded group has no eligible work, the next group is claimed
    **immediately** — the 600 s idle-stop never delays a cross-model switch;
  - fairness: after `model_batch_max_jobs` / `model_batch_max_seconds` on the
    loaded group, or when another group has a job older than
    `max_model_queue_wait_seconds` (`priority_aging_enabled`), the other group
    goes next. Never interrupts an in-flight generation.
- **Claim-then-LREM**: the PostgreSQL lease (`claim_attempt`) is the race guard;
  Redis is trimmed afterwards (delivery hint, not truth). A lost race removes
  the stale hint. If the peek path finds nothing, the worker falls back to
  blocking BRPOP (idle efficiency preserved).
- `workers.loaded_model` (migration 0036) reports the resident checkpoint.

### B. Swappiness + capacity — `scripts/autoscale.py`, `app/fleet_settings.py`

`MODEL_SWAPPINESS` (0–100, default 50) controls remote provisioning:

- 0 = depth-only policy (no cost-benefit gate); 25/50/75/100 = thresholds.
- Gate (every scale-up attempt, all outcomes logged to `gpu_scale_decisions`):
  `auto_burst_enabled` → `EXISTING_REMOTE_CAPACITY` (max_auto_burst_workers) →
  `BUDGET_EXHAUSTED` (daily budget) → compare estimated local wait
  (`queued_work_seconds` spread over capacity) vs remote readiness
  (`OAL_REMOTE_READY_SECONDS`, default 360 s) with advantage
  `1.5 − swappiness/100` → `REMOTE_FASTER` / `REMOTE_STARTUP_TOO_SLOW`.
- Fleet settings persist as `SiteSetting` JSON (`gpu_fleet_settings`),
  validated by `app/fleet_settings.py`; the autoscaler reads the DB with a
  60 s cache, env vars are bootstrap defaults.

### C. Unified provisioning coordinator — `gpu_deployments` (migration 0037)

- One Vast CLI owner: the autoscaler tick fulfils durable intents
  (`REQUESTED → PROVISIONING → READY/FAILED`); the admin API only writes them.
- Manual deploys: `origin=MANUAL_ADMIN`, `automatic_shutdown=false` by default,
  idempotency key (double-click safe), offer revalidation at deploy time
  (`OFFER_UNAVAILABLE` / `OFFER_CHANGED` vs the $/h ceiling), budget guard.
- Routine scale-down never destroys a manual worker (`manual_contracts()`).
- Auto nodes record `AUTO_BURST` deployments for cost categories;
  `gpu_fleet_events` is the audit trail.

### D. Offer discovery — `app/vast_offers.py`

Vast **REST** search (no CLI in the API container) → hard filters (price
ceiling $0.25 default, VRAM, CUDA 12.8+, US/CA, verified, reliability ≥95%,
disk) → documented weighted ranking (compatibility 0.30, readiness 0.20,
cost 0.20, performance 0.15, network 0.05, reliability 0.05, disk 0.05).
Missing provider fields display as **Not reported** and never disqualify
(network scores neutral 0.5). Top-10 endpoint caches searches server-side
for 30 s across admin sessions.

### E. Fleet console — `frontend/src/pages/admin/GpuFleet.tsx`

Admin → GPU Fleet: Overview, Smart Queue (per-model waits, loaded checkpoints),
Settings (swappiness slider + burst/budget controls, dirty-state Save),
Top-10 Offers (refresh, cached badge, deploy confirmation), Deployments,
Instances, Costs (categories + today estimate), Events (decisions + audit).

## Admin API

```
GET    /api/v1/admin/gpu-fleet                     overview
GET    /api/v1/admin/gpu-fleet/queues              per-model waits + workers + depths
GET|PATCH /api/v1/admin/gpu-fleet/settings         fleet settings (validated)
GET    /api/v1/admin/gpu-fleet/offers              Top-10 live offers (?refresh=true)
POST   /api/v1/admin/gpu-fleet/deployments         manual deploy intent (idempotent)
GET    /api/v1/admin/gpu-fleet/deployments[/{id}]  deployment tracking
POST   /api/v1/admin/gpu-fleet/workers/{id}/stop|restart   (?force=true)
DELETE /api/v1/admin/gpu-fleet/workers/{id}        destroy (busy-guarded)
GET    /api/v1/admin/gpu-fleet/costs               today + categories
GET    /api/v1/admin/gpu-fleet/events              decisions + audit
```

## Environment

`OAL_REMOTE_READY_SECONDS` (360), `OAL_SCALE_FAMILY_FACTORS`,
`OAL_SCALE_MAX_DPH`; scheduler knobs are `Settings` fields
(`scheduler_peek_window`, `model_batch_max_jobs/_seconds`,
`max_model_queue_wait_seconds`, `priority_aging_enabled`).

## Baseline vs target

Pre-implementation (7 d, hub): avg queue wait 124.5 s, max 3097 s, 572 jobs.
Post-deploy targets: fewer cross-model swaps, lower max wait, explainable
provisioning decisions in `gpu_scale_decisions`.

## Rollback

Revert the merge commit; migrations 0036/0037 are additive (drop columns/tables
in downgrade). With `auto_burst_enabled=false` + `swappiness=0` the system
behaves exactly like the pre-M2 autoscaler; SMQM falls back to BRPOP on any
peek failure.
