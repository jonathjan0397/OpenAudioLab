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
9. Private artifacts expire after seven days by default. Download links expire sooner and cannot outlive artifact retention.
10. No credentials, model weights, generated music, production database dumps, or customer lyrics in Git.
11. No cloud spending or production deployment without configured authorization and limits.
12. Append implementation decisions and validation evidence to `DEVELOPMENT_LOG.md`; keep OpenAPI and frontend examples aligned.

Deliver implementation in reviewed milestones and a feature branch. Do not merge or deploy automatically. Routine local development and tests do not require repeated permission. Ask only when missing deployment facts block the next milestone.
