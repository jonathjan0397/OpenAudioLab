# Custom-track artist profiles and training

## UAIS replacement (2026-10-21, implemented)

The experimental rights/dataset/training-run/evaluation flow below was replaced by the
**Universal Artist Identity System (UAIS)** as a hard replace (old experimental rows were
dropped in migration `0033_uais`; no customer data existed). Current truth:

- Tables: `voice_profiles`, `voice_datasets`, `voice_recordings`, `voice_dataset_versions`,
  `voice_adapters`, `voice_analyses`. `artist_profiles.default_voice_profile_id` points at
  the active voice profile; `loras.adapter_id` binds published style models to adapters.
- Pipeline: create dataset → upload recordings (ffmpeg QC: clipping/silence/energy/decode;
  SHA-256 dedupe) → freeze an immutable dataset version (frozen SHA-256; older adapters go
  `stale`) → optional `voice.analyze` (`mfcc-stats-v1` embeddings; analysis artifact only,
  never a conditioning input) → `voice.train` (50 credits) → `voice.validate` (10 credits,
  similarity vs configurable threshold default 0.5 — calibration default, not science).
- Jobs: operations `voice.analyze` / `voice.train` / `voice.validate` on the durable job
  system; queues `oal:queue:training` (2B) and `oal:queue:training-xl` (4B XL).
- Compatibility per model selection (`app/uais/capabilities.py` manifests +
  `app/uais/resolver.py`): `NATIVE_ADAPTER_READY`, `ADAPTER_VALIDATION_REQUIRED`,
  `REFERENCE_CONDITIONING_AVAILABLE`, `ADAPTER_TRAINING_REQUIRED`, `PREPARING`,
  `UNSUPPORTED`, `FAILED`. Only `ace-step-1.5-turbo` has `adapter_load_verified=true`;
  SFT/XL/merge are honest unverified states. Unknown licenses fail closed.
- Generation binding: `artist_id` + `voice_fidelity` (`native|reference|best`) or an
  explicit `voice_adapter_id` (mutually exclusive with `lora_id` and with each other).
  The resolved plan is frozen into the job (`request_json._voice`); reference plans run
  `task_type=cover` with the artist's reference asset. No silent fallback between methods.
- Frontend: Voice Studio page (`/voice`) drives dataset, freeze, analyze, train, validate,
  adapters and the compatibility matrix; the create widget binds the workspace artist's
  default adapter when it matches the selected model.

Phases E/F (implemented 2026-10-21): `voice.analyze` now separates vocals per recording
when the worker has a separator (Demucs adapter today; VIPE/SVC can replace it behind the
same `Separator` interface) — the vocal stem is stored as a derived `training_stem` asset,
recorded on the recording (`vocal_asset_id`, `separation_json`), and used as the embedding
input (`input_type: vocal_stem`; honest `full_mix` fallback with reason when no separator
is configured). Training itself still conditions on full mixes (ACE-Step distribution);
separation serves identity analysis/validation, not a relabeled training input. The
resulting `voice_profile.identity_json` carries a **genre-independence estimate**: mean
cross-recording embedding consistency (different songs as a genre/style proxy) — an
estimate with its basis recorded, never a quality score or a measured genre transform.
The sections below are the original capability planning; where they mention
`datasets`/`training_runs`/`evaluations` tables or `/activate`, UAIS supersedes them.

## Purpose and truthful capability reporting

Users can create private artist profiles from authorized custom music tracks. Style and singer identity are separate optional components, combinable at generation time only where the selected engine supports the combination. Profiles cannot guarantee an exact singer or style match merely because references have been uploaded.

| Mechanism | Actual operation | Result designation |
| --- | --- | --- |
| Reference conditioning | Retain references and supply them during inference | `reference_conditioning`; no weight training |
| Style extraction | Analyze instrumentation, arrangement, voice/production features | `style_profile`; no weight training |
| Model fine-tuning | Optimize supported adapter/checkpoint parameters using a versioned dataset | `fine_tuned_adapter` or `fine_tuned_checkpoint` |

Fine-tuning is a required product capability to validate, not a claim that the initially selected music engines support a production-ready training recipe. Complete a training feasibility gate before selecting its base model. If none meets licensing, quality, hardware and inference-loading requirements, report the gap; do not relabel reference conditioning as training.

## Backend workflow

1. Create an owned artist profile with separate musical-style and singer components.
2. Create a dataset and issue short-lived scoped uploads. Accept original tracks, optional vocal/instrumental stems, supplied lyrics/transcripts, language, section labels and descriptive tags.
3. Record owner authorization/rights declarations for recordings, compositions and singer identity as applicable. No public voice impersonation or cross-user dataset access by default. Declarations are evidence records, not proof of ownership or a model-license substitute.
4. Finalize uploads only after content validation, checksum, duration and format probing. Check duplicates by hash and near-duplicates where implemented; flag clipping, silence, noise and source quality. Reject malformed audio and unsupported sizes.
5. Prepare a reproducible dataset: segment audio, align supplied text when supported, optionally transcribe or separate stems with approved models, and publish a quality report. Derived transcriptions are training annotations, never replacements for submitted generation lyrics. Preserve original recordings and labels.
6. Freeze a dataset version. Split training/validation/holdout by original recording and near-duplicate group, not random neighboring segments; avoid evaluation leakage. Minimum/maximum duration, sample requirements and supported labels come from the selected training recipe, not invented universal thresholds.
7. Submit a training job referencing profile, immutable dataset, approved base revision, recipe revision and bounded resource budget. Validate compatibility and reserve training allowance atomically before execution.
8. Train in an isolated worker with lease fencing, checkpoints, metrics, bounded logs, cancellation and documented resume support. Training queues have separate GPU allocations from inference queues; interactive generation is not silently starved.
9. Register the result as a candidate profile version. Evaluation generates fixed-prompt samples and compares to the base model and holdout targets using available measurements plus listening review. Training and evaluation have separate recorded outcomes.
10. An authorized owner activates a specific evaluated version. Keep the previous active version for rollback. Activation uses optimistic concurrency; failed or incomplete candidates cannot become active.

The frontend implements upload/profile/dataset forms, progress displays, sample players, review controls and activation UI. No such interface is built in this repository. The backend exposes those operations as authenticated services.

## Data records and compatibility

- `artist_profiles`: owner, name, components, sharing policy, active version per compatible engine, timestamps.
- `artist_profile_versions`: immutable version ID, mechanism, base engine/revision, recipe, dataset version, artifacts, evaluation status, activation/retirement state, compatibility and provenance.
- `datasets` / `dataset_versions`: source asset IDs/checksums, labels, preparation recipe, split manifest, report, rights records, frozen version hash.
- `training_runs`: common job/attempt ID plus budget, hyperparameters, seed, resume checkpoint, worker/hardware, metrics and artifact references.
- `evaluations`: candidate/base references, fixed prompts, holdout IDs, measurements, comparison assets and owner review.
- `rights_records`: owner declaration, source association, permitted purpose and revision/date; restricted visibility.

Adapters/checkpoints are engine-specific. A profile version trained for one base model must not load into another base/revision unless an explicit tested compatibility rule exists. Generation requests freeze the resolved profile version; changing the active profile later cannot alter an existing job. Fine-tuning jobs can use supplied labels or approved transcription tooling without a lyric-generation LLM.

## Compute, budgets and recovery

Require server-enforced maximum GPU time, wall-clock time, storage/checkpoint size and permitted worker class. Estimates are labeled estimates. Separate training allowance from generation credits; record reservations, actual usage and settlement/release under a documented policy. Automatic retries are off by default for expensive training; explicit retry/resume retains dataset/base/recipe snapshots and revalidates remaining budget. Do not provision paid cloud resources implicitly.

Worker reports must include actual optimization steps and artifact hashes before a run is called trained. A checkpoint file alone does not establish quality. Loadable-artifact verification and at least one real inference with the candidate are mandatory acceptance checks. Unsafe pickle/code payloads cannot be uploaded by users as trusted executable models; internally created checkpoints use reviewed safe-loading formats/paths.

## Privacy, retention and deletion

User tracks and training material remain private and are not pooled for shared model training without separate explicit opt-in. Profile sharing does not imply dataset sharing. Logs exclude raw audio, credentials and full lyric texts.

Active profile artifacts, needed preprocessing metadata and compatibility manifests do not expire with seven-day generated outputs. Dataset source retention is an explicit owner policy: keep while needed or delete after preparation/training with a warning that retraining/reproducibility may no longer be possible. Never delete source tracks silently. Temporary segments, abandoned runs and obsolete checkpoints have separate bounded retention. Training source/quota policies and output retention must be recorded before deployment.

Deletion immediately revokes new use/access, cancels or drains dependent work under policy and queues idempotent storage cleanup. Workers must acknowledge unload/cache eviction; stale leases cannot republish deleted material. Report pending deletion until object stores, worker caches and documented backup-expiry policy are addressed. Existing generated songs are separate assets; deleting a profile does not silently delete its songs. Do not claim deleting a dataset removes its influence from already trained weights; delete/retire derived profile versions when requested.

## Required tests and feasibility evidence

Verify cross-user dataset/profile isolation; immutable versions; true split separation; rights-record persistence; malformed/duplicate data handling; budget cutoff; cancellation/resume policy; fenced callbacks; native training metrics; checkpoint loading; candidate inference; explicit activation and rollback; incompatible-model rejection; and deletion/cache invalidation.

Run at least one complete real custom-track training/evaluation/generation cycle on actual hardware. Record engine and recipe versions, authorized test dataset, duration, peak memory, training/runtime cost, output quality and limitations. Synthetic jobs or reference-conditioned samples cannot satisfy the fine-tuning gate.
