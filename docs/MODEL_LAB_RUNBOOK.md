# Model Lab / GPU Fleet operator runbook (pipeline M1–M8)

Backend-only. Everything below is API-driven; the separate frontend owns lyrics.

## 1. Vertical slice: import → registered adapter

1. `POST /api/v1/admin/model-lab/sources` + `POST .../sources/{id}/import` — scan
   and register recordings (ffprobe metadata only; no LLM touches audio).
2. `POST /api/v1/admin/model-lab/recordings/{id}/review` — approve/reject.
3. `POST /api/v1/admin/model-lab/datasets` — freeze an approved selection
   (immutable manifest + frozen SHA-256).
4. `PUT /api/v1/admin/model-lab/budget` — pilot budget (default 6 h / $3).
5. `POST /api/v1/admin/model-lab/datasets/{id}/train` — reserves the estimate
   atomically and enqueues `model_lab.train` (202). Zero headroom = 409, never
   silent overspend.
6. Worker runs the pinned trainer (`OAL_MODEL_LAB_TRAIN_COMMAND`) with
   continuous lease heartbeat, cancellation and a hard wall deadline
   (`OAL_MODEL_LAB_RUN_WALL_HOURS`). A successful no-op fails
   (`TRAINING_NO_ARTIFACT`).
7. Tail: export to `ml/adapters/<attempt>/…`, optional engine reload
   (`OAL_MODEL_LAB_RELOAD_ENABLED`), register as a `kind=adapter` candidate
   bundle. Budget settles exactly once (idempotent).

## 2. Exclusive training on a fleet node

- Node identity is durable (`OAL_NODE_KEY`, default hostname) and survives
  Vast instance churn: `GET /api/v1/admin/gpu-fleet/nodes`.
- States: `shared_ready → draining → training_reserved → active → cleanup →
  shared_ready`; any → `quarantined`. Transitions are conditional UPDATEs: the
  claim-vs-reservation race has exactly one winner.
- Admin: `POST .../nodes/{key}/drain|quarantine|reset`. The worker supervisor
  quarantines stale heartbeats (`OAL_NODE_STALE_SECONDS`, default 180 s).
- Shared inference may only land on `shared_ready` nodes.

## 3. Offers, deploy, cost ledger

- `GET /api/v1/admin/gpu-fleet/offers` — filters: `min_vram` (≥24 GB floor),
  `max_dph`, `country`, `min_reliability`, `min_download`/`min_upload`
  (server-side inet pre-filter), `gpu_model`, `min_disk`, `min_ram`,
  `verified`, `limit` (1–50), `refresh`.
- `GET/PUT /admin/gpu-fleet/presets` — named searches (unique names).
- `POST /admin/gpu-fleet/deploy` — deployment form: durable REQUESTED
  deployment + pending instance + open ledger entry. Provider create is only
  claimed once a funded rental exists.
- Lifecycle uses the documented Vast contract: `PUT /instances/{id}/`
  `{"state": "shutdown"|"running"}`, `DELETE` for destroy. Stop/destroy close
  the ledger entry (exact hours × dph); restart closes and reopens.
- `GET /admin/gpu-fleet/ledger` — entries + closed totals by purpose.

## 4. BYOL singer identity (config-gated)

- Set `OAL_VOICE_IDENTITY_CHALLENGER=byol-v1` **and**
  `OAL_BYOL_MODEL_PATH` (pinned weights, baked at `/opt/byol/byl-light.pt`)
  **and** `OAL_BYOL_SCAN_COMMAND` (prints `{"vector": [...]}` for a crop;
  receives `OAL_CROP_START`/`OAL_CROP_WINDOW`).
- Missing configuration fails closed — no silent mfcc fallback. Calibration
  against the pilot catalog is still pending (no real-GPU verification yet).

## 5. Merges, routing, releases

- Merge recipes accept 0/1/many adapters (zero = anchor-only control);
  `params.strengths` must be one 0..1 value per adapter and reaches the worker
  as `OAL_ML_STRENGTHS`.
- `POST /merge-recipes/{id}/run` → 202 `building` bundle + `model_lab.merge`
  worker job (never runs in the API process).
- Exact-bundle routing: `POST /jobs` with `bundle_id` fails explicitly
  (`BUNDLE_NOT_FOUND` / `BUNDLE_NOT_AVAILABLE`) — never a silent substitute.
- Promotion gate: released + satisfactory verdict (win/pass) + artifact
  integrity; a `fail` verdict disqualifies. Promotion enforces the gate.
- Channels: `PATCH` `enabled`/`min_credits`/`canary_percent`;
  `GET .../resolve?owner_id=&credits=` returns the routing decision with a
  machine-readable reason; `POST .../rollback` swaps to the previous bundle.
- Bundles archive from retired/candidate/failed (`POST /bundles/{id}/archive`).

## 6. Still unverified (needs funded rental / real GPU)

- Real Vast create/price behaviour for the deploy form.
- Trainer/merge command numerical outputs on hardware (strength × delta).
- BYOL embedding quality/calibration on the pilot catalog.
- AcoustID client key (identification provider) unset in production.
