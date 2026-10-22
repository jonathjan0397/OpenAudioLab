# Pipeline implementation report (M1–M8) — 2026-10-22

Branch `feat/model-lab-pipeline`, commits `4050589..HEAD`. Validation: 423
backend tests + 17 frontend tests, frontend build clean. Capability statuses:
**implemented** (code exists) · **fixture-tested** (automated tests with
fixtures/mocks) · **integration-tested** (real dependencies) ·
**real-GPU-verified** · **production-enabled**.

| Capability | Status | Notes |
| --- | --- | --- |
| Worker `model_lab.train` (no NameError, heartbeat, cancel, wall deadline) | fixture-tested | tests/test_model_lab_m1_repairs.py |
| Budget reservation + idempotent settlement (0044) | fixture-tested | headroom = max − (spent+reserved+est) |
| Trainer no-op fails (TRAINING_NO_ARTIFACT) | fixture-tested | |
| Worker-side merge builds (building→candidate/failed) | fixture-tested | API never runs merge subprocess |
| Promotion gate (satisfactory verdict + integrity) | fixture-tested | enforced transactionally by promote |
| Vast lifecycle PUT/DELETE contract | fixture-tested | live offer search verified earlier against real Vast |
| Swappiness hard gates at sw==0 | fixture-tested | autoscale |
| Fleet-node identity + exclusive state machine (0045) | fixture-tested | conditional-UPDATE race guard |
| Supervisor quarantine (stale heartbeat) | fixture-tested | worker loop tick |
| Offer filters gpu_model/min_disk/min_ram | fixture-tested | server-side query + client gate |
| Named offer presets | fixture-tested | site_settings blob |
| Deployment form (REQUESTED + ledger open) | implemented | provider create unverified (no rental) |
| GPU cost ledger (0046, exact close, idempotent) | fixture-tested | |
| Vertical slice import→register | fixture-tested | tests/test_model_lab_m4_slice.py |
| Async `model_lab.identify` | fixture-tested | provider calls mocked; AcoustID key unset in prod |
| Caption compiler (deterministic, no LLM) | fixture-tested | |
| BYOL challenger gate + encoder hook | implemented | weights baked in worker image; calibration pending |
| Merge strengths contract (0..1 per adapter) | fixture-tested | numerical verification pending real GPU |
| Exact-bundle routing on /jobs | fixture-tested | BUNDLE_NOT_FOUND / BUNDLE_NOT_AVAILABLE |
| Creation Cards | fixture-tested | |
| Channel canary + rollback + resolve | fixture-tested | deterministic owner-hash bucket |
| Bundle archive state | fixture-tested | |
| Admin Nodes panel + ledger view (frontend) | fixture-tested | GpuFleet "Nodes" tab |
| Real-GPU training run (pinned recipe on Vast) | real-GPU-verified (earlier milestones) | this run added no rental |
| Production model promotion | pending owner go | no auto-promotion |

Explicitly **not** done this run (by decision): Vast rental spend, production
model promotion, BYOL calibration data, AcoustID client key.

Migrations applied on deploy: 0044 (reservations), 0045 (fleet_nodes),
0046 (gpu_cost_ledger), 0047 (channel canary/history).
