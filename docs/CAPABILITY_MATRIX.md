# OpenAudioLab Capability Matrix

Status legend:
- **Done+Tested** — implemented and verified in this branch/session.
- **Present** — code/test surface exists from prior milestones; not re-verified end-to-end this session.
- **Incomplete** — partially built; UI/schema may exist but the real capability or acceptance evidence is missing.
- **Engine-blocked** — not possible with the deployed Turbo worker without provisioning the required model/asset pipeline (must NOT be faked).
- **Not-wired** — valid upstream control/task that the adapter does not yet forward (needs a typed bridge).

See `docs/ACE_STEP_CONTROL_PARITY.md` for the field-level audit.

## Spec section status

| # | Area | Status | Evidence / gap |
|---|---|---|---|
| 0 | Generation-submission CONTROL_UNSUPPORTED blocker | **Done+Tested** | `feat/generation-contract`: `description`/`styles` removed from controls; `tests/test_generation_contract.py` proves rejection-with-details + acceptance; frontend build green; serializer executed for idea-only/style-only/both |
| 2 | Creator→engine contract; strict validation kept; first-class idea/style/caption/lyrics | **Done+Tested** (core) | `song_idea`/`style_prompt` typed fields persisted; exact untrimmed lyrics + real provenance (`human` vs `frontend_llm`); singer folded into caption; shift relabeled+disabled (Turbo no-op); `docs/ACE_STEP_CONTROL_PARITY.md` |
| 1 | Error envelope (unknown/supported controls, request_id, safe details) | **Done** | `frontend/src/api.ts::ApiError.controlHint()` surfaces rejected+supported field names; draft preserved |
| 3 | Simple+Advanced parity, custom duration (185/190/210), cost/queue/progress visible | **Incomplete** (Phase 1 done) | Phase 1: registry is the single capability source; control values range/type-validated (`CONTROL_INVALID`); base-only `shift` rejected on Turbo; `time_signature` accepted+forwarded+in card; capability-driven serializer + `vitest` (9 tests); numeric BPM/key/time/language/shift present. Full Advanced parity still gated by 3B |
| 3A | Remix / vocal swap / melody swap / repaint / extension / extract / lego / complete | **Backend done (cover/cover-nofsq/repaint)**; UI pending; extract/lego/complete **out of scope (Turbo)** | `feat/phase2-source-conditioned`: typed `task_type`/`src_asset_id`/`reference_asset_id` + cover/repaint controls; admission validates task support + asset ownership + region bounds; worker stages owned audio under the engine-allowed temp path and forwards `src_audio_path`/`reference_audio_path`/`audio_cover_strength`/`cover_noise_strength`/repaint fields; captured in the durable manifest. Engine-verified: real cover on Turbo produced source-honored audio. Studio source-picker UI + repaint-region audition still to build |
| 3B | Exhaustive ACE-Step Advanced control surface | **Not-wired** | ~40 valid REST fields + retake/flow-edit/velocity/cot_* not in the transport; audit produced, bridge + UI not built |
| Phase3 | Multi-model catalog/entitlements/quotes/model-aware routing | **Turbo + SFT + XL-SFT + XL-Turbo live & audio-validated** | Serialized GPU-0 worker-managed swap; SFT renders on acestep-v15-sft (engine_version proven), Turbo unaffected & swaps back; quotes+entitlement+lineage live. XL (4B DiT) is a first-class pinned-runtime model (upstream issue #990/PR #989): the 4B DiT is ~9 GB bf16 but the full engine (DiT + Qwen3 text encoder + VAE) peaks ~20.6 GiB without offload, so XL runs on the shared 24 GB baseline worker with `ACESTEP_OFFLOAD_TO_CPU=1` (DiT resident, text encoder/VAE CPU-offloaded, no perf hit) + the llama-server fully on CPU (`OAL_LLM_GPU_LAYERS=0`); audio-validated at **19.7 GB peak** (flash-attn unavailable → SDPA). Community merge remains unconfigured pending exact repo/revision/license. |
| 3C | Real-audio acceptance gates for remix/vocal/melody/repaint/extract | **Blocked** | Depends on 3A/3B; requires authorized GPU + compatible checkpoints |
| 4 | Structured AI Songwriting Assistant (sections/lines, typed) | **Present/Incomplete** | `/llm/draft|lyrics|title|style-prompt` exist; typed section/line schema + duration-aware completeness + truncation repair not verified this session |
| 5 | Exact lyrics + independent styles throughout | **Done+Tested** | Backend verbatim-lyrics test passes; serializer emits exact text + independent fields |
| 6 | Immutable Creation Card (requested/resolved/effective, lineage) | **Present/Incomplete** | `request_json` persists; full per-take seed/hash/model-config/stem lineage card not verified this session |
| 7 | Recreation / Edit / Studio reliability; job+asset workspace save | **Present** | Studio hydration updated to read `song_idea`/`style_prompt` + legacy fallback; broader fixes unverified |
| 8 | Measured stem quality (htdemucs_6s vs ft vs RoFormer, profiles) | **Present/Incomplete** | `separator.py`, `audio_processing.py`, features/admin routes exist; benchmarked profiles + source-aligned validation not verified |
| 9 | Artist identities, cards, public pages, socials | **Present** | `routes/artist.py`, `Artist.tsx`; full branding/links/visibility not re-verified |
| 10 | Fair homepage artist discovery | **Present** | `test_m13_social` spotlight/stats exist; randomization fairness not re-verified |
| 11 | Custom voice profiles per artist (training) | **Present** | `training_worker`, LoRA, artist routes; end-to-end + leak isolation not re-verified |
| 12 | Guest limits + server identity + atomic reservations | **Done+Tested (prior)** + present | `quota.py`, guest reservation in `jobs.py`; rejection path verified this session makes no reservation |
| 13 | Beginner pricing + ledger accounting | **Present** | `billing.py`, guest-beginner merge (`9d70eaf`); exactly-once grant/idempotent events not re-verified |
| 14 | Signup + published policies | **Present** | `auth.py`, `policies`, acceptance in `jobs.py`; live email/CSRF not verified |
| 15 | Administrator dashboard completeness | **Present/Incomplete** | `routes/admin.py`, `Admin.tsx`; per-action wiring audit not completed |
| 16 | End-to-end verification + evidence | **Partial** | Backend 206 tests pass, frontend builds; live/browser/audio gates remain |

## Verified this session
- Backend: `pytest` **206 passed** (3 new generation-contract tests).
- Frontend: `tsc -b && vite build` succeeds under `strict` + `noUnusedLocals`.
- Serializer executed against the pinned model (idea/style/both, instrumental, shift, seeds, provenance).

## Remaining blockers (stated precisely)
- **3A/3B/3C**: require an adapter typed-bridge for `src_audio_path`/`reference_audio_path`/
  `audio_code_string`/`task_type`/repaint controls, a source-asset upload→probe→stage pipeline
  with ownership at every reference, and a **base-family checkpoint** for extract/lego/complete
  (Turbo cannot run them). No real remix/vocal/melody audio may be claimed until these land and
  are auditioned through authorized workers.
- **Payments/subscription exactly-once, live email, browser/E2E, audio benchmarks**: external
  integrations/hardware not exercised here.
