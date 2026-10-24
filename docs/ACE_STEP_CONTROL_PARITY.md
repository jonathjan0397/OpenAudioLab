# ACE-Step Control Parity Audit

Authoritative source: pinned ACE-Step 1.5 commit `ca1e85fe9430179831e6bc6be790c332190a3866`
(verified live from the deployed worker image, `git -C /opt/acestep rev-parse HEAD`).
Reference model: `acestep/api/http/release_task_models.py::GenerateMusicRequest` (the
`/release_task` REST contract the OpenAudioLab adapter actually calls).

Statuses:
- **forwarded** — OpenAudioLab sends this to the adapter today.
- **accepted-noop** — accepted by the registry but not forwarded by the adapter.
- **not-wired** — valid upstream control the adapter does not yet expose (needs a typed bridge).
- **turbo-noop** — forwarded/valid but documented as having no effect on the deployed Turbo model.
- **model-blocked** — the deployed Turbo worker cannot run this task; needs a base-family model provisioned.

## Disposition of every `GenerateMusicRequest` field

| Upstream field (aliases) | Type / default / range | OAL status | Notes |
|---|---|---|---|
| `prompt` | str "" | forwarded | = resolved `music_description` (non-lyric caption) |
| `global_caption` | str "" | not-wired | SFT-stems `lego` global context |
| `lyrics` | str "" | forwarded | exact approved lyrics only |
| `thinking` | bool false | forwarded | DiT-only path keeps false |
| `sample_mode` | bool false | not-wired | LM auto caption/lyrics; would violate approved-lyrics invariant if default-on |
| `sample_query` | str "" | not-wired | paired with `sample_mode` |
| `use_format` | bool false | not-wired | must never rewrite approved lyrics |
| `model` | str null | forwarded | pinned `acestep-v15-house-turbo` / `acestep-v15-turbo` |
| `bpm` | int null | forwarded | |
| `key_scale` | str "" | forwarded | upstream name `keyscale`/`key_scale` |
| `time_signature` | str "" | forwarded | accepted+forwarded (Phase 1); UI exposes "Time sig" in Advanced |
| `vocal_language` | str "en" | forwarded | |
| `inference_steps` | int 8 | forwarded | OAL "Quality" preset default 8 == upstream default |
| `guidance_scale` | float 7.0 | forwarded | only when non-zero from UI |
| `use_random_seed` | bool true | forwarded | derived from seed presence |
| `seed` | int/str -1 | forwarded | explicit null-handling preserved for seed 0 |
| `reference_audio_path` | str null | not-wired | **style/timbre reference** — Section 3A source/reference roles |
| `src_audio_path` | str null | not-wired | **source audio** for cover/repaint/extract/lego/complete — 3A blocker |
| `audio_duration` | float null | forwarded | custom duration incl. 185/190/210 (guest cap enforced server-side) |
| `batch_size` | int null | forwarded | from `variations` (1–4) |
| `repainting_start` | float 0.0 | not-wired | 3A repaint |
| `repainting_end` | float null | not-wired | 3A repaint |
| `instruction` | str DEFAULT_DIT_INSTRUCTION | not-wired | "Fill the audio semantic mask based on the given conditions:" |
| `audio_cover_strength` | float 1.0 | not-wired | 3B — distinct from cover_noise_strength (must not be merged into a "Weirdness" slider) |
| `cover_noise_strength` | float 0.0 | not-wired | 3B — 0=pure noise, 1=closest to source |
| `audio_code_string` | str "" | not-wired | explicit source codes; precedes LM codes |
| `task_type` | str "text2music" | not-wired | Turbo/SFT support text2music, repaint, cover, cover-nofsq; base adds extract, lego, complete |
| `chunk_mask_mode` | enum auto {explicit,auto} | not-wired | 3A repaint |
| `repaint_latent_crossfade_frames` | int 10 | not-wired | 3A boundary blend |
| `repaint_wav_crossfade_sec` | float 0.0 | not-wired | 3A crossfade |
| `repaint_mode` | enum balanced {conservative,balanced,aggressive} | not-wired | 3A |
| `repaint_strength` | float 0.5 (0–1) | not-wired | only in balanced mode; polarity to be resolved via runtime path |
| `analysis_only` | bool false | not-wired | admin/diagnostic |
| `full_analysis_only` | bool false | not-wired | admin/diagnostic |
| `extract_codes_only` | bool false | not-wired | 3A code control |
| `use_adg` | bool false | not-wired | applicability varies by checkpoint |
| `cfg_interval_start` | float 0.0 | not-wired | 3B |
| `cfg_interval_end` | float 1.0 | not-wired | 3B |
| `infer_method` | str "ode" (ode|sde) | not-wired | 3B |
| `shift` | float 3.0 (1–5) | rejected-on-turbo | registry excludes it from Turbo `supported_controls`; API returns CONTROL_UNSUPPORTED for it on Turbo; UI disabled+relabeled; serializer only emits it when a model declares it applicable (base) |
| `timesteps` | str null | not-wired | overrides inference_steps+shift; precedence to expose |
| `dcw_enabled` | bool null | not-wired | model-resolved default; forced-on non-turbo distorts (issue #1259) |
| `dcw_mode` | enum double {low,high,double,pix} | not-wired | expert |
| `dcw_scaler` | float 0.05 | not-wired | expert |
| `dcw_high_scaler` | float 0.02 | not-wired | expert |
| `dcw_wavelet` | str "haar" | not-wired | expert |
| `audio_format` | str "mp3" | forwarded (fixed "wav") | OAL locks wav mix; mp3 derived from lossless in export path |
| `use_tiled_decode` | bool true | not-wired | runtime/memory profile |
| `lm_model_path` | str null | not-wired | runtime profile (5Hz LM selection) |
| `lm_backend` | enum vllm {vllm,pt,mlx} | not-wired | runtime profile |
| `constrained_decoding` | bool true | not-wired | planning |
| `constrained_decoding_debug` | bool false | not-wired | redacted/diagnostic |
| `use_cot_caption` | bool true | forwarded (off when not thinking) | planning provenance |
| `use_cot_language` | bool true | forwarded (off when not thinking) | planning provenance |
| `is_format_caption` | bool false | not-wired | caption action |
| `allow_lm_batch` | bool true | not-wired | batching |
| `track_name` | str null | not-wired | model registry list: woodwinds, brass, fx, synth, strings, percussion, keyboard, guitar, bass, drums, backing_vocals, vocals |
| `track_classes` | list null | not-wired | complete/lego track classes |
| `lm_temperature` | float 0.85 | not-wired | 5Hz planning |
| `lm_cfg_scale` | float 2.5 | not-wired | 5Hz planning |
| `lm_top_k` | int null | not-wired | 5Hz planning |
| `lm_top_p` | float 0.9 | not-wired | 5Hz planning |
| `lm_repetition_penalty` | float 1.0 | not-wired | 5Hz planning |
| `lm_negative_prompt` | str "NO USER INPUT" | not-wired | 5Hz planning |

## Source conditioning (Phase 2 — implemented + engine-verified)

`src_audio_path` / `reference_audio_path` are now forwarded by the adapter. The pinned
engine's `release_task_audio_paths.validate_audio_path` **rejects absolute paths outside
the system temp dir** (and any `..` traversal), so the worker stages owned source audio
under `OAL_ASSET_STAGE_DIR` (default `/tmp/oal-asset-stage`) — a content-hashed file the
co-located ACE-Step server can read — and passes that absolute temp path. Browser clients
only ever send owned `asset_id`s; ownership is checked at admission and re-checked at
staging. Verified end-to-end at ca1e85f on the deployed Turbo model: a `cover` job with
`task_type=cover` + a real staged `src_audio_path` produced a real 15 s WAV (the source was
honored); `extract/lego/complete` remain base-model-only and are not offered.

## Controls named in the spec but NOT present in the `/release_task` REST model

These live only at `GenerationParams`/Gradio level and therefore require a **reviewed typed
worker bridge**; they cannot be shipped today and are marked **not-wired / needs-bridge**:

- `retake_seed`, `retake_variance` (retake / controlled variation)
- `flow_edit_morph`, `flow_edit_source_caption`, `flow_edit_source_lyrics`,
  `flow_edit_n_min`, `flow_edit_n_max`, `flow_edit_n_avg` (source-to-target morph is an
  overlay, not a native `edit` task)
- `velocity_norm_threshold`, `velocity_ema_factor`, `latent_shift`, `latent_rescale`
  (verified absent from this REST model; internal/Gradio only)
- `cot_bpm`, `cot_keyscale`, `cot_timesignature`, `cot_duration`, `cot_vocal_language`,
  `cot_caption`, `cot_lyrics` — generated planning metadata; surfaced read-only, never to
  overwrite approved inputs
- `seeds`, `lm_batch_chunk_size`, `use_constrained_decoding`, `sample_query` batch variants

## Task / model compatibility (verified at ca1e85f)

- `TASK_TYPES` = text2music, repaint, cover, cover-nofsq, extract, lego, complete
- `TASK_TYPES_TURBO` = text2music, repaint, cover, cover-nofsq
- `TASK_TYPES_BASE` adds extract, lego, complete
- Deployed worker model = `acestep-v15-turbo` (and promoted `acestep-v15-house-turbo`, same
  Turbo family). **Extract / Lego / Complete are model-blocked** on the current worker and
  require provisioning a base-family checkpoint, not UI simulation.

## OpenAudioLab control-bag contract (post-repair)

The public `controls` map is validated against `app/registry.py::supported_controls` and must
equal what the adapter forwards. For `ace-step-1.5` (Turbo) the accepted+forwarded set is:
`mood, gender, bpm, key_scale, time_signature, vocal_language, inference_steps,
guidance_scale, variations`. `shift` is excluded and returns `CONTROL_UNSUPPORTED`
on Turbo (it is base-family only). `mood` and `gender` are stamped on the finished
asset's tag list (`orchestration.complete_generation`) for discovery — they do not
mutate the engine prompt. The free-text song **idea** (`song_idea`) stays
recipe/manifest metadata. The **style** lane (`style_prompt`) is folded into the
engine caption at render time: `engine_worker._style_text_for` resolves it through
the versioned taxonomy (`style_tags.resolve_style_text`), replacing matched aliases
with canonical subgenre captions, passing unmatched words through, dropping junk
tokens; the caption sent upstream is `music_description + ", " + resolved_style`
trimmed to 2000 chars, and lyrics remain a separate untouched field. Control
**values** are additionally range/
type-validated (`CONTROL_INVALID`) so a slider can't ship an out-of-range number.

## Catalog `model_selection` path (multi-model, post-Phase3)

The statements above describe the legacy single `model_id` (`ace-step-1.5` Turbo) path, which is
unchanged. The newer `model_selection` path (`ace-step-1.5-{turbo,sft,xl-sft,xl-turbo,merge-…}`)
validates controls against the per-model `ExecutionProfile` in `app/catalog.py::validate_profile_controls`
and forwards the **resolved** controls (profile defaults filled for anything the caller omits) so the
engine runs the correct per-model denoising settings instead of its REST default of 8 steps. Notable
differences from the legacy path:
- **Non-turbo guidance/steps** are set to upstream recommendations — sft 64 steps (50-100)/CFG 7.0
  (5-9)/shift 1.0; xl-sft 100/CFG 7.0/shift 1.0; merge 64/CFG 7.0/shift 1.0; DCW forced off. Turbo-family
  locks 8 steps + CFG 1.0 (distilled) and uses shift 3.0; xl-turbo DCW matches the 2B turbo default (on).
- **`shift` is a profile-owned band** (turbo 1-3, base 1-3), so it is accepted on Turbo *profiles*
  here, unlike the legacy Turbo `model_id` (which still rejects it as base-only).
- `sampler_mode` (euler/heun) remains unsupported: the pinned REST `GenerateMusicRequest` has no such
  field, so it is rejected and `infer_method` (ode/sde) is used instead.
