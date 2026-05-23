# Development Rules

## Governance

1. Read `OPENAUDIOLAB_MASTER_PLAN.md` before making changes
2. Follow the current backend-first build priority
3. Preserve all abstractions (pipeline, workers, storage, security, model packs)
4. Update `DEVELOPMENT_LOG.md` for every task

## Non-Negotiables

- Custom lyrics are preserved exactly as submitted
- Lyric reasoning runs for AI-generated lyrics
- No default production credentials
- Worker registration requires token
- Generated files are private with configurable retention
- Backend is model-agnostic
- No polished final UI before backend orchestration works

## Development Log

A task is NOT complete until `DEVELOPMENT_LOG.md` has been updated.

See `AGENTS.md` for the full log entry template.
