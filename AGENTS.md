# Coding-agent instructions

Read all planning documents and `CODING_AGENT_HANDOFF.md` before implementation. The user requires a standalone API backend on port 50555. The separate frontend owns lyric generation and its LLM connection.

## Invariants

1. Never generate, reason over, revise, humanize, or silently normalize lyrics using an LLM in this backend. Preserve the submitted Unicode string exactly, including spaces and line endings; record a SHA-256 of its UTF-8 bytes.
2. Keep inference out of API processes. Keep CUDA/model dependencies out of the base API image.
3. Durable database records are authoritative. Queue messages are delivery hints, not the source of job truth.
4. Every job and artifact operation enforces user ownership; workers have distinct, scoped credentials and assignment leases.
5. Reject unavailable or unsupported model options explicitly. Never silently route a paid request to another engine, CPU tone, or cloud provider.
6. Use real stage progress when available; otherwise return an indeterminate stage. Do not invent completion percentages.
7. Test tones are development fixtures, clearly marked `synthetic_test_audio`, never music-generation success.
8. Model revisions, license evidence, capabilities, and worker requirements are explicit. Unknown licenses fail closed for commercial dispatch.
9. Generated output artifacts expire after seven days by default under the deployment policy. Active artist-profile artifacts and explicitly retained training datasets have separate retention; never apply output cleanup to them. Download links cannot outlive the relevant asset.
10. No credentials, model weights, generated music, production database dumps, or customer lyrics in Git.
11. No cloud spending or production deployment without configured authorization and limits.
12. Append implementation decisions and validation evidence to `DEVELOPMENT_LOG.md`; keep OpenAPI and frontend examples aligned.

13. Backend services only: no frontend application, website, player, dashboard, timeline/mixer UI, lyric chatbot or checkout UI. API schemas and examples are in scope.
14. Required exports are WAV and MP3 mixes and aligned WAV stems; follow `docs/OUTPUT_SPEC.md`.
15. Reference conditioning and style analysis are not fine-tuning. Actual custom-track training requires a verified recipe, budget, evaluation and compatible versioned artifacts.
16. Read `docs/SERVICE_CATALOG.md`, `docs/ARTIST_TRAINING.md` and `docs/OUTPUT_SPEC.md` as mandatory scope documents.

This baseline is capability planning. Begin runtime implementation only when assigned the coding-agent implementation phase. Deliver implementation in reviewed milestones and a feature branch. Do not merge or deploy automatically. Routine local development and tests do not require repeated permission. Ask only when missing deployment facts block the next milestone.
