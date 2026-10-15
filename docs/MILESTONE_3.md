# Milestone 3 — First real music engine (ACE-Step 1.5)

Status: **complete** on branch `impl/milestone-1` for the local GPU hardware.
Not merged to `master`; not deployed. Date: 2026-10-15.

## Deployment facts recorded (milestone-0 items closed)

- Host: this server, 3x NVIDIA RTX PRO 4000 Blackwell (24 GB, sm_120), driver
  610.57.04, Docker `nvidia` runtime present.
- Engine runtime (isolated from the API venv): upstream `ACE-Step-1.5` at
  commit `ca1e85f` (2026-08-29), Python 3.12, torch 2.10.0+cu128 (CUDA 12.8),
  installed with `uv sync`; checkpoints `ACE-Step/Ace-Step1.5` (28 files,
  size-verified) in `checkpoints/`.
- License evidence: MIT code (upstream LICENSE); MIT model card
  https://huggingface.co/ACE-Step/Ace-Step1.5 — checked 2026-10-15. Registry
  entry pinned to revision `1.5.0@ca1e85f`, `license_status=verified`.
- Upstream server: `acestep-api` on private port 8001, DiT-only
  (`ACESTEP_INIT_LLM=false`), GPU 0.

## Scope delivered

- `app/engine_acestep.py`: adapter over the documented REST contract
  (`/release_task`, `/query_result`, `/v1/audio`). Lyrics are passed verbatim;
  lyric rewriting/formatting is disabled (`use_format=false`) and, in DiT-only
  mode, caption/language CoT is disabled so no LM mutates inputs. Seed and
  duration map to `use_random_seed`/`seed`/`audio_duration`; output format is
  native WAV; batch size 1.
- `app/engine_worker.py`: isolated worker process. Claims with a fenced lease,
  submits, polls (polling doubles as the heartbeat), honors cancellation
  (upstream has no cancel endpoint — late results are discarded;
  `upstream_termination_supported=false`), downloads, validates the WAV, and
  finalizes one non-synthetic asset. `ENGINE_BUSY` requeues without burning the
  attempt budget; failures map to safe codes (`ENGINE_REJECTED`, `ENGINE_AUTH`,
  `ENGINE_BUSY`, `ENGINE_GENERATION_FAILED`, `ENGINE_TIMEOUT`,
  `ENGINE_NO_AUDIO`, `ARTIFACT_INVALID`).
- Registry: ACE-Step 1.5 duration range enforced at admission (10–600 s,
  matching the upstream `audio_duration` contract); model detail exposes
  `min_duration_seconds`.
- Compose `ace` profile: private `acestep-server` (GPU device 0, checkpoint
  volume, healthcheck) + `engine-worker`; `Dockerfile.acestep` provided as the
  deployment deliverable (the benchmarked runtime is the host venv; the image
  build itself is not yet benchmarked).
- Redis client fix: redis-py >=6 defaults `socket_timeout=5s`, which raced the
  5 s blocking BRPOP; the queue factory now pins `socket_timeout=None` with a
  health check, and the dependency is held at the `5.*` line.

## Real-generation evidence (this host, GPU 0)

| Run | Result | Wall time | Notes |
| --- | --- | --- | --- |
| Cold vocal (first task, lazy model init) | succeeded | ~10 s | 30 s target, seed 7 |
| Warm vocal (same seed) | succeeded | 3 s | deterministic seed honored |
| Instrumental | succeeded | 2 s | 20 s target, empty lyrics |
| Full pipeline job #1 (API→dispatcher→worker→API) | succeeded, attempt 1 | ~15 s | lyrics hash recorded on job |
| Full pipeline job #2 (post redis fix) | succeeded, attempt 1 | ~15 s | zero worker errors |

- Native output: 48 kHz stereo WAV, 5,760,078 bytes for the 30 s job;
  SHA-256 recorded; served through the public API with 200 (full) and 206
  (Range) and decoded with the stdlib WAV reader.
- Asset metadata: `synthetic_test_audio=false`, role `mix_wav`, sample rate
  48000, channels 2, duration 30.0, seven-day expiry.
- VRAM: ~12.3 GB used on GPU 0 by the DiT-only server (no LM).

## Acceptance gates

| Gate (docs/IMPLEMENTATION_PLAN.md) | Result | Evidence |
| --- | --- | --- |
| Real vocal song from supplied lyrics through the public API | Pass | job `ec587af5` succeeded; WAV decoded and delivered |
| Real instrumental (if supported) | Pass | instrumental job succeeded (20 s WAV) |
| Benchmark evidence saved | Pass | table above; hardware + image/commit recorded |
| Native output metadata + input lyric hash | Pass | asset metadata + `lyrics_sha256` |
| Cold-start readiness | Pass | `/health` before load; first task initializes |
| Out-of-memory handling | Partial | upstream failures map to `ENGINE_GENERATION_FAILED`; no forced OOM injection yet |
| Timeout behavior | Implemented | `ENGINE_TIMEOUT` path unit-tested; not triggered live |
| Worker drain | Implemented | cooperative stop flag; not exercised under load |

## Validation run

- `pytest tests -q` → 68 passed (10 new engine tests: payload mapping with
  verbatim Unicode lyrics, submit/poll lifecycle, unknown task, download,
  busy-requeue, generation failure, cancel-during-poll, happy path with
  `synthetic=false`).
- Live pipeline on PostgreSQL 16 + Redis 7 (Compose) with the host engine
  worker against the real upstream server: vocal and instrumental jobs
  succeeded end-to-end; artifacts downloadable with Range support.

## Known limits / deferred

- DiT-only configuration (`thinking=false`): the 5Hz LM planning mode is
  available but not enabled; enabling it adds the LM checkpoint and VRAM.
- MP3 and stem exports are milestone 4 (audio worker); generation delivers the
  native WAV mix only.
- `Dockerfile.acestep` image build is untested; the validated runtime is the
  pinned host venv. Vast.ai deployment will use the same images.
- Upstream cancellation is discard-only (no task-cancel endpoint in the
  reviewed contract); remote compute may continue after our cancellation.
