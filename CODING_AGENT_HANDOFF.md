# Master handoff to the implementation agent

You are implementing the standalone OpenAudioLab music-generation backend. Repository: `jonathjan0397/OpenAudioLab`, default branch `master`. Read `AGENTS.md`, all `docs/` planning documents, and `DEVELOPMENT_LOG.md` first. Capability baseline: v0.3-container-plan. The owner required finishing capabilities before implementation; this commit is specification only.

## User-approved scope

Create an API-driven music-generation service that the independently hosted OpenAudioLab.io frontend reaches through port **50555**. The frontend maintains its own separate LLM connection for lyric generation. Accept finalized lyrics and music direction here; this backend must never call, require, or duplicate that lyric LLM. This repository contains backend services only. Do not build any website, dashboard, player, timeline/mixer UI, checkout UI, lyric chatbot or frontend LLM integration. API documentation and developer/client examples are appropriate.

## Your first action

When assigned implementation, inspect the target environment and frontend integration configuration, then record a concrete implementation checklist against the milestones. Confirm the host, HTTPS ingress, exact frontend origins, identity provider/token contract, persistent storage, GPU topology and first engine. Do useful independent milestone-1 work while deployment facts are gathered. Do not request broad confirmation for routine reversible coding, but do not guess production secrets or provision paid GPUs.

## Build order

0. Establish deployment facts and independently verify a viable custom-track training recipe.
1. Contract, FastAPI/configuration on 50555, migrations, auth and owner isolation.
2. Durable jobs/outbox, queue, worker leases, cancellation, retries, private artifacts and usage ledger.
3. Real generation adapter and GPU validation with exact release/license evidence.
4. Backend projects/versions, uploads, analysis, processing, WAV/MP3 and aligned WAV-stem exports; external frontend contract/client tests.
5. Custom-track dataset preparation, true fine-tuning, evaluation, compatible profile versions and explicit activation/rollback.
6. Supported continuation, section replacement, variations, remixes and offline mixing renders.
7. Optional engines, operational hardening and prioritized advanced backend services.

Mandatory scope documents: `docs/SERVICE_CATALOG.md`, `docs/OUTPUT_SPEC.md`, `docs/ARTIST_TRAINING.md`. Full mixes must support WAV and MP3; individual stems must be WAV, with a complete ZIP option. Keep exports traceable to the same mix version and report native versus separated stems.

Users must be able to train profiles from their authorized custom tracks. Reference conditioning, style extraction and actual fine-tuning are different mechanisms. Verify a licensed, supported recipe before committing to a base model. Profiles separate musical style from singer identity. Train with explicit budgets, isolated workers, frozen datasets, holdout evaluation and versioned compatible artifacts. Never label uploaded references or a synthetic task as completed training. Active profile artifacts and explicit dataset retention are not covered by seven-day output cleanup.

Use PostgreSQL and Redis, preserving storage and worker abstractions. Keep inference dependencies in isolated workers. Use a generic adapter contract internally, but never assume upstream models expose that contract. MiniMax's documented SGLang endpoint accepts lyrics as `input` and musical direction as `instructions`; verify current documentation and exact runtime requirements before implementation.

## Deliverable behavior

Through APIs the external frontend can discover engines, submit final lyrics/music direction, receive an accepted job ID immediately, observe honest progress, cancel or retry, and obtain authorized audio access. It can manage projects/versions, upload references, request WAV/MP3 and WAV-stem exports, and submit/evaluate/activate artist-profile training. The API stays responsive during GPU inference. A deployment with no GPUs can run the API and explicit test worker without falsely claiming real generation.

All user-supplied and frontend-LLM lyrics remain exactly as received. Do not inherit the old monorepo's backend lyric-reasoning or rewriting requirement. Its default 8000 mapping, unaudited authorization, placeholder mastering/stems, generic VRAM assumptions and synthetic generation are not evidence of compliance with this plan. The owner explicitly abandoned the old scaffold and authorized reusing this repository. Build from this new root-level baseline; do not continue the abandoned nested `openaudiolab/` implementation.

Create an implementation branch and deliver milestone-sized commits/PRs. Keep development logging current. Report meaningful validation and blocked hardware checks honestly. Do not merge the implementation to master, deploy, migrate production or spend on cloud resources as part of this handoff.

## Definition of done

Every acceptance gate in `docs/IMPLEMENTATION_PLAN.md` is either demonstrated or explicitly blocked with a concrete reason; blocked gates remain unmet requirements. At least one actual music model must generate valid audio through the API before calling music generation implemented. At least one real custom-track fine-tuning/evaluation/inference cycle is required before calling artist training implemented. The final report identifies remaining adapters/stubs, training feasibility gaps, operating instructions and settings for the separate frontend. Documentation and generated OpenAPI agree.


## Mandatory container and runtime decision

Read docs/CONTAINER_RUNTIME_PLAN.md. Build a Docker service stack, not a single all-model environment. Deliver core/API on 50555 plus isolated audio, separation, dataset, inference and training workers with Compose deployment profiles. ACE-Step 1.5 is the primary generation and documented headless LoRA/LoKr training candidate. HeartMuLa uses its own heartlib/codec worker; MiniMax optionally uses SGLang-Omni under conditional policy and documented GPU allocation. Additional engines remain deferred unless selected. Keep upstream UIs disabled and engine endpoints private. Benchmark/pin before declaring any training or generation production-ready. Internal music-engine LMs must never replace the frontend lyric LLM or rewrite approved lyrics.
