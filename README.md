# OpenAudioLab Backend

Backend planning baseline for OpenAudioLab.io in `jonathjan0397/OpenAudioLab`.

Status: capability specification and coding-agent handoff only (v0.2-capabilities). No running API, model adapter, deployment, or GPU benchmark is claimed.

## Fixed requirements

- Backend entry point: port **50555**.
- Frontend is independently deployed and maintains its own LLM integration for lyric generation.
- Backend accepts finished lyrics and music direction; it must not call a lyric LLM or rewrite supplied lyrics.
- Asynchronous music generation, private audio delivery, progress tracking, cancellation, and retry.
- Backend services only: no website, dashboards, player, timeline editor, checkout UI, or lyric chatbot.
- Required outputs: WAV and MP3 full mixes, individual aligned WAV stems, and stem ZIP packages.
- Private custom-track artist profiles with separate reference, style-analysis and real fine-tuning mechanisms.
- Model-agnostic adapters; local and remote GPU workers.
- ACE-Step 1.5 is the proposed first unrestricted-commercial engine; MiniMax Music 3 is an optional, conditionally licensed engine.

## Read in order

1. `AGENTS.md`
2. `docs/SERVICE_CATALOG.md` — scope and frontend/backend boundary
3. `docs/ARCHITECTURE.md`
4. `docs/API_CONTRACT.md`
5. `docs/OUTPUT_SPEC.md`
6. `docs/ARTIST_TRAINING.md`
7. `docs/MODEL_POLICY.md`
8. `docs/IMPLEMENTATION_PLAN.md`
9. `CODING_AGENT_HANDOFF.md`

The owner requested capability planning before implementation. This revision records the expanded scope and leaves runtime implementation for the coding-agent phase. Advanced/model-dependent services are planned targets, not currently available features.

The previous scaffold is abandoned by the owner. This baseline replaces its files on the existing `master` branch; the previous implementation remains recoverable in Git history. Do not restore or continue the old pipeline. In particular, its backend lyric-generation/reasoning requirement is superseded by the frontend's separate LLM connection.

Repository visibility is unchanged from the existing repository. No new project-wide source license is selected by this reset; audit any prior licensing obligations before reusing historical code. Model licenses are separate from application-source licensing.
