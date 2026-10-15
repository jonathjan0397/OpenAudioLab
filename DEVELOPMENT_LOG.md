# Development log

## 2026-10-15 — Repository reset and standalone API backend planning

Author: Codex. Task type: planning and handoff.

Prepared the backend architecture, API contract, model licensing policy, milestone acceptance gates, and implementation-agent instructions for the existing repository. Fixed the public backend boundary at port 50555 and placed lyric generation entirely in the independent frontend's LLM integration. The owner explicitly authorized abandoning and clearing the prior scaffold, reusing `jonathjan0397/OpenAudioLab`. Replace its 157 tracked files with this documentation baseline using a normal commit whose parent is `b272ff2e66e0c00fd3a015afa41333dc63f0c53a`. Previous code and its development log remain in history; Git history is not rewritten.

Created: README.md, AGENTS.md, CODING_AGENT_HANDOFF.md, docs/ARCHITECTURE.md, docs/API_CONTRACT.md, docs/MODEL_POLICY.md, docs/IMPLEMENTATION_PLAN.md, DEVELOPMENT_LOG.md and .gitignore.

Validation: planning-document consistency and required boundary checks only. Application tests, deployment and GPU generation have not run; no application implementation is included.

Next: implementation agent starts milestone 0 on a feature branch. This reset does not rename the repository or change its visibility. Hostname, frontend auth configuration, GPU inventory and actual model benchmarks remain unknown.


## 2026-10-15 — Backend capabilities, required outputs and artist training specification

Author: Codex. Task type: capability planning. User authorized proceeding with the specification after confirming backend-only separation and custom-track artist training.

Created: docs/SERVICE_CATALOG.md, docs/OUTPUT_SPEC.md, docs/ARTIST_TRAINING.md.

Updated: README.md, AGENTS.md, CODING_AGENT_HANDOFF.md, docs/ARCHITECTURE.md, docs/API_CONTRACT.md, docs/MODEL_POLICY.md, docs/IMPLEMENTATION_PLAN.md and this log.

Defined the frontend/backend responsibility boundary and backend service inventory: generation/editing, uploads, project/version data, analysis/DSP/renders, exports, jobs/workers, profiles/datasets/training/evaluation, quotas/usage and administration. Confirmed WAV/MP3 full mixes, aligned WAV stems and ZIP packaging. Separated reference conditioning/style extraction from actual fine-tuning, style from singer identity, active-profile retention from generated-output expiry, and training from inference allocations. Added API shapes and acceptance gates for budgeted real training, evaluation and activation.

Validation: Markdown links/read-order, fenced JSON examples, document inventory, port/lyric/backend-only boundaries, output requirements, training semantics and immutable-profile compatibility reviewed. No application tests, generation, fine-tuning or deployment ran; this commit contains documentation only.

Open decisions: deployment host/TLS, external identity configuration, GPU inventory, verified training base/recipe, measured quality/cost and saved-output retention beyond existing seven-day default. Advanced/model-dependent capabilities remain conditional until proven. No frontend was created and implementation remains pending a coding-agent assignment.


## 2026-10-15 — Docker service topology and model runtime planning

Author: Codex. Task type: architecture planning.

User requires Docker containerization for portable local/cloud deployment. Added docs/CONTAINER_RUNTIME_PLAN.md and aligned README, AGENTS, architecture, model policy, milestones and coding-agent handoff. Specified primary ACE-Step inference/training, isolated HeartMuLa, optional SGLang-Omni MiniMax, dedicated separation/audio/dataset/evaluation workers, private ports, persistence, GPU allocation and Compose profiles. Official ACE-Step docs now provide a headless LoRA/LoKr training path; it remains an untested operational candidate. Final lyrics must bypass upstream text rewriting.

Checks: source documentation reviewed; read-order/port/boundary/runtime consistency checked. No Docker builds, inference, training, cloud provisioning or deployment ran. Remaining gates: pinned compatible image/runtime/checkpoints, exact hardware and real model/training validation.
