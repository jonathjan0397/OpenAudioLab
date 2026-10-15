# Master handoff to the implementation agent

You are implementing the standalone OpenAudioLab music-generation backend. Repository: `jonathjan0397/OpenAudioLab`, default branch `master`. Read `AGENTS.md`, all `docs/` planning documents, and `DEVELOPMENT_LOG.md` first.

## User-approved scope

Create an API-driven music-generation service that the independently hosted OpenAudioLab.io frontend reaches through port **50555**. The frontend maintains its own separate LLM connection for lyric generation. Accept finalized lyrics and music direction here; this backend must never call, require, or duplicate that lyric LLM. The user requested planning and a GitHub handoff before implementation; this replacement baseline is documentation only.

## Your first action

Inspect the target environment and frontend integration configuration, then record a concrete implementation checklist against the milestones. Confirm the host, HTTPS ingress, exact frontend origins, identity provider/token contract, persistent storage, GPU topology and first engine. Do useful independent milestone-1 work while deployment facts are gathered. Do not request broad confirmation for routine reversible coding, but do not guess production secrets or provision paid GPUs.

## Build order

1. Contract, FastAPI/configuration on 50555, migrations, auth and owner isolation.
2. Durable jobs/outbox, queue, worker leases, cancellation, retries, private artifacts and expiry.
3. Real ACE-Step 1.5 adapter and GPU validation, with exact release/license evidence.
4. Frontend integration contract/client, polling then authenticated SSE.
5. Optional model adapters; MiniMax Music 3 is conditionally licensed and disabled until requirements are configured.

Use PostgreSQL and Redis, preserving storage and worker abstractions. Keep inference dependencies in isolated workers. Use a generic adapter contract internally, but never assume upstream models expose that contract. MiniMax's documented SGLang endpoint accepts lyrics as `input` and musical direction as `instructions`; verify current documentation and exact runtime requirements before implementation.

## Deliverable behavior

A frontend user can discover available engines, submit final lyrics/music direction, receive an accepted job ID immediately, observe honest progress, cancel or retry, and play/download authorized audio. The API stays responsive during GPU inference. A deployment with no GPUs can run the API and explicit test worker without falsely claiming real generation.

All user-supplied and frontend-LLM lyrics remain exactly as received. Do not inherit the old monorepo's backend lyric-reasoning or rewriting requirement. Its default 8000 mapping, unaudited authorization, placeholder mastering/stems, generic VRAM assumptions and synthetic generation are not evidence of compliance with this plan. The owner explicitly abandoned the old scaffold and authorized reusing this repository. Build from this new root-level baseline; do not continue the abandoned nested `openaudiolab/` implementation.

Create an implementation branch and deliver milestone-sized commits/PRs. Keep development logging current. Report meaningful validation and blocked hardware checks honestly. Do not merge the implementation to master, deploy, migrate production or spend on cloud resources as part of this handoff.

## Definition of done

Every acceptance gate in `docs/IMPLEMENTATION_PLAN.md` is either demonstrated or explicitly blocked with a concrete reason. At least one actual music model must generate valid audio through the API before calling music generation implemented. The final report identifies remaining adapters and stubs, operating instructions and frontend settings. Documentation and generated OpenAPI agree.
