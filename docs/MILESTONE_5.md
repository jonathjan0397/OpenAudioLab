# Milestone 5 — Artist profiles and real LoRA fine-tuning on hardware

Status: **complete** on branch `impl/milestone-1` for the local stack.
Not merged to `master`; not deployed. Date: 2026-10-15.

## Scope delivered

- **Schema** (Alembic `0004`): `artist_profiles`, `rights_records`, `datasets`,
  `dataset_tracks`, `dataset_versions`, `artist_profile_versions`,
  `training_runs`, `evaluations`. Profile versions are immutable and carry
  mechanism, base model/revision, recipe revision, dataset version, artifacts,
  evaluation status and activation state; profiles keep an active-version
  pointer for rollback.
- **Artist API** (`app/routes/artist.py`): owner-scoped profile CRUD with
  integer-ETag concurrency; rights declarations (recordings/composition/singer
  identity, evidence records only); datasets with track add + `finalize` that
  assigns each recording to `train`/`validation`/`holdout` (split by recording
  unit, not random segments) and freezes a `frozen_sha256`; `trainings` with
  pre-queue budget validation (`BUDGET_EXCEEDED`); `evaluations`; `activate`
  (409 `PROFILE_NOT_EVALUATED` until measured) and `review`.
- **Training adapter** (`app/training_acestep.py`): upstream ACE-Step training
  REST contract — `/v1/init`, `/v1/dataset/scan`, `/v1/dataset/preprocess`,
  `/v1/training/start|status|stop|export`, `/v1/lora/load|unload|toggle`.
- **Training worker** (`app/training_worker.py`): isolated process on
  `oal:queue:training` / `oal:queue:evaluation` with fenced leases,
  poll-as-heartbeat, cancellation, budget guard, candidate registration and
  evaluation measurements. Recipe `acestep-lora@ca1e85f`.
- **Profile-aware generation**: admission resolves the active profile version
  (`PROFILE_VERSION_NOT_FOUND` / `PROFILE_INCOMPATIBLE`); the engine worker
  loads the candidate LoRA for the job and unloads after, so a generation with
  an active profile actually uses the trained adapter.
- **Live gate driver** (`scripts/training_cycle.py`): stdlib-only end-to-end
  custom-track cycle. Compose gained a `training-worker` service in the `ace`
  profile.

## Upstream integration findings (real hardware)

- The upstream training path-safety root is the server's working directory, so
  `OAL_TRAIN_WORKDIR` must live under the engine checkout
  (`.../ACE-Step-1.5/training-data`); absolute paths outside it are rejected.
- The trainer nests the PEFT output at `lora/final/adapter/`; the worker
  resolves the adapter directory rather than assuming the export root.
- Upstream keeps adapter names registered after `unload`, so every load uses a
  unique `adapter_name` and unloads first; the base-vs-candidate evaluation
  comparison toggles `use_lora` (`/v1/lora/toggle`) instead of unload/reload.
- The DiT lazy-loads on first generation; preprocessing needs it, so the worker
  calls `/v1/init` before scanning a dataset.

## Live cycle evidence (this host, real engine)

`scripts/training_cycle.py` against the running stack (PostgreSQL 16 + Redis 7
+ host API/dispatcher/engine worker/training worker + ACE-Step server on an
RTX PRO 4000 Blackwell):

| Step | Result |
| --- | --- |
| 3 custom-track generations | succeeded (training material) |
| Profile + rights + 3 tracks | created; dataset frozen `645190aa45b5…` |
| LoRA optimization | succeeded; **24.0 s** wall clock |
| Candidate registered | `fine_tuned_adapter`, recipe `acestep-lora@ca1e85f` |
| Evaluation (toggle base-vs-candidate) | succeeded; **6.0 s**, `measured` |
| Activation | active version, previous retained for rollback |
| Generation with active profile | succeeded (candidate LoRA loaded) |

Activated profile version (PostgreSQL): mechanism `fine_tuned_adapter`, base
`1.5.0@ca1e85f`, recipe `acestep-lora@ca1e85f`, `evaluation_status=measured`,
`state=active`, `adapter_loadable=true`, final loss 1.2937, hardware
`ai-server01`.

## Acceptance gates

| Gate (docs/ARTIST_TRAINING.md) | Result | Evidence |
| --- | --- | --- |
| Complete real training/eval/generation cycle | Pass | `TRAINING CYCLE OK` (table above) |
| True split separation (holdout by recording) | Pass | finalize assigns by recording unit |
| Budget cutoff | Pass | `BUDGET_EXCEEDED` pre-queue |
| Native training metrics | Pass | steps/loss recorded on the run |
| Loadable-artifact verification | Pass | `adapter_loadable=true` via real load |
| Candidate inference | Pass | generation with active profile |
| Explicit activation + rollback | Pass | activate/previous retained |
| Incompatible-model rejection | Pass | `PROFILE_INCOMPATIBLE` admission |
| Cross-user isolation | Pass | owner-scoped routes (tests) |
| Fenced callbacks / cancellation | Pass | lease-fenced worker paths (tests) |

## Validation run

- `pytest tests -q` → 93 passed (10 new artist/training tests).
- Live cycle: `TRAINING CYCLE OK` (table above).
- Migration `0004` applied to the live PostgreSQL.

## Known limits / deferred

- Dataset `finalize` freezes a split + checksum; segmentation, transcription and
  stem preparation are recorded as annotations, not run (deferred).
- Budgets are simple caps (max epochs / wall-clock) validated before queuing;
  reservation/settlement accounting is a later operations milestone.
- Resume/checkpoint-restart is not implemented; automatic retry is off for
  training (explicit re-submit only).
- Evaluation measurements are fixed-prompt candidate-vs-base samples plus
  owner review; no automatic quality score is claimed.
- Training and inference share the single validated host GPU here; separate
  GPU allocations for training vs inference queues are a deployment concern.
