# Docker deployment and model runtime specification

Version: 0.3-container-plan. Planning only; no images have been built or GPU workloads tested. Containerized deployment is a user requirement. Use multiple independently deployable services rather than one image containing all models and infrastructure.

## Required service boundaries

| Service | Runtime / image responsibility | Network / scaling |
| --- | --- | --- |
| api | Python/FastAPI/Uvicorn; auth, contracts, admission, model/profile discovery | Only public application entry point, port 50555; CPU; stateless replicas |
| dispatcher | Outbox publication, scheduling, lease reconciliation | Private; CPU; database-coordinated claims |
| postgres | PostgreSQL; migrations and persistent authoritative records | Private; persistent volume or external managed service |
| redis | Broker/cache, not authoritative job storage | Private; persistent/configured broker policy or managed service |
| object-storage | Private S3-compatible store for standalone Compose, or managed object storage | Scoped signed object access; admin endpoints private |
| audio-worker | Reviewed FFmpeg/ffprobe build plus Python audio/DSP packages | Private CPU work queue; analysis, processing, mixing, WAV/MP3/ZIP exports |
| separation-worker | Pinned Demucs/PyTorch runtime and approved checkpoint | Private GPU/CPU capability; WAV stems; separately scaled |
| dataset-worker | Audio probing/segmentation, metadata/splits, model-specific preprocessing | Private; CPU plus explicit GPU preprocessing allocations as needed |
| training-worker-acestep | Headless ACE-Step LoRA/LoKr training and checkpoint production | Private GPU training queue; separate limits/devices from inference |
| evaluation-worker | Fixed evaluation jobs and orchestration of inference/analysis | CPU coordinator; requests already allocated inference capacity, no hidden GPU access |
| maintenance | Retention/deletion, dataset cleanup, export housekeeping | Private scheduled jobs; idempotent work claims |
| migrate | One-shot schema migration with deployment lock | Runs once per rollout; not every API replica |

Model-specific inference services below are separate images. A queue adapter may run beside/in the engine worker image and supervise a private upstream server process. Do not duplicate GPU model loads by starting multiple API server workers. FastAPI control-plane replicas do not load model weights.

## Model runtimes and activation policy

### ACE-Step 1.5 — primary generation and first training implementation

Use upstream Python/PyTorch runtime and documented headless REST server, launched through the upstream acestep-api entry point. Upstream API defaults to port 8001; keep it private. Adapter maps public jobs to documented task submission (/release_task) and result querying (/query_result), then ingests validated audio into owned storage. These are upstream routes, not public OpenAudioLab routes.

Package inference in engine-acestep and training in training-worker-acestep, using independently pinned dependencies and GPU resource assignments. Training uses upstream documented /v1/training/start and /v1/training/start_lokr through a private training-only instance, or reviewed Python training entry points. Validate preprocessing, progress/stop, artifact loading and version-specific behavior before enabling a recipe. Do not expose upstream filesystem-path parameters to clients. No Gradio UI is deployed.

Consider turbo for fast inference and base/SFT for capability-specific tasks or training, but pin/test exact checkpoints rather than assuming adapters interchange across variants. Upstream availability of training code narrows the feasibility gap; it does not prove production-quality style or singer adaptation.

ACE-Step's internal 5Hz musical planning model may require its own checkpoint and PyTorch or vLLM backend, depending on the tested deployment. This is a music-engine component, not the frontend's lyric-generation LLM. Disable simple-mode lyric creation, lyric rewriting, automatic formatting and any text-completion path that mutates supplied lyrics. Pass approved lyrics verbatim, record their hash, and test captured upstream payloads. Do not equate disabling all musical planning with preserving lyrics: verify version-specific controls independently.

Sources:
- https://github.com/ace-step/ACE-Step-1.5
- https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/API.md
- https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/INFERENCE.md
- https://github.com/ace-step/ACE-Step-1.5/blob/main/docs/en/LoRA_Training_Tutorial.md

### HeartMuLa — additional lyric-conditioned generation engine

Use isolated engine-heartmula with official heartlib Python/PyTorch pipeline, HeartMuLa model and matching HeartCodec checkpoints/configuration. Wrap the documented Python interface in our worker adapter; a universal upstream REST API is not assumed. Upstream dependency ranges and pinned transformer/codec-related packages justify a separate environment from ACE-Step.

Load only the generation components required by the selected task. Optional HeartTranscriptor/other models require separate capability and memory accounting. Do not infer trainability merely from torchtune appearing in dependencies. Headless inference, exact checkpoint pairing and measured device placement are acceptance gates.

Sources:
- https://github.com/HeartMuLa/heartlib
- https://github.com/HeartMuLa/heartlib/blob/main/pyproject.toml

### MiniMax Music 3 — optional, conditional-commercial engine

Use engine-minimax backed by the officially documented SGLang-Omni runtime, pinned to a compatible revision. Its documented server uses port 8000 and /v1/audio/speech; worker supplies lyrics as input and musical description as instructions and receives WAV. Upstream non-streaming operation is compatible with our asynchronous public jobs; do not promise streaming music generation.

The documented SGLang path uses two CUDA GPUs. Reserve both as one allocation and validate each device's VRAM, host RAM and runtime compatibility. This is a requirement of this selected execution path; do not generalize it to every alternative implementation. No public training API/recipe is established by the reviewed documentation: no MiniMax artist fine-tuning capability is advertised until separately verified.

Keep disabled until commercial attribution/policy requirements are configured. ComfyUI is an optional alternative runtime for a later validated adapter, not a required shared host for every model. Do not deploy its frontend UI or assume its hardware needs match SGLang-Omni.

Source: https://github.com/MiniMax-AI/MiniMax-Music3

### Demucs — first dedicated stem-separation candidate

Use separation-worker with isolated PyTorch/Demucs, a reviewed maintained source revision, and a separately license-checked official checkpoint. Select htdemucs only after the release/weight checks. It separates an existing mix; these stems must be labeled separated, not native generation. Preserve alignment and WAV output requirements.

The original Meta repository is archived/not actively maintained; evaluate the author's maintained fork and dependency compatibility before pinning. CPU separation may be allowed only as an explicitly advertised slower capability, not a concealed fallback.

Sources:
- https://github.com/facebookresearch/demucs
- https://github.com/adefossez/demucs

### Deferred runtime adapters

DiffRhythm 2 and original YuE v1 remain optional candidates, not baseline mandatory images. If activated, give each a pinned Python/PyTorch worker environment with official inference/preprocessing/codecs and its own capacity profile. YuE v1 requires its complete staged pipeline; YuE2 is not a license-equivalent upgrade. Do not deploy every researched model by default.

Optional transcription/alignment models for training annotations or lyric quality checks run as explicit analysis capabilities with their own revisions/license/memory records. They do not generate lyrics.

## Audio-processing runtime

Use FFmpeg/ffprobe for conversion, probing and supported loudness/filter operations; Python soundfile/NumPy/SciPy/librosa as needed for analysis/preparation; a reviewed loudness measurement implementation where appropriate. Verify distribution obligations for the precise FFmpeg build. Do not install arbitrary unrelated audio packages.

Native WAV preservation, MP3 export including 320 kbps, aligned WAV stems, safe ZIP packaging and the OUTPUT_SPEC.md manifest are required. Mastering/DSP recipes are versioned and explicit, not synonyms for a file copy. Separate GPU inference/training from CPU conversion workers.

## GPU and dependency strategy

Initial supported deployment target: Linux amd64 with NVIDIA CUDA. Host supplies a compatible NVIDIA driver and NVIDIA Container Toolkit; GPU access is explicitly configured in Compose/provider deployment. Container CUDA libraries must be compatible with the host driver. Docker cannot supply missing physical GPUs or convert a CPU-only host into a GPU node.

Pin each engine's base image digest, Python, PyTorch/CUDA combination, upstream source commit, lockfile and checkpoint hashes. Versions will be set by the coding agent after a compatibility build; this specification intentionally does not fabricate a universal CUDA/PyTorch version. No floating latest images in production. No automatic upgrades on boot.

Use runtime images without compilers for ordinary inference where possible; multi-stage builds and a separate training image accommodate build tools. Do not require privileged mode or mount the Docker socket into public services. GPU ownership is enforced by scheduler/device allocation, not by a Redis queue name alone.

References:
- https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html
- https://docs.docker.com/compose/how-tos/gpu-support/

## Internal adapter and storage contract

The API writes durable work; dispatch chooses compatible workers. Engine adapters implement validate, readiness/capabilities, submit-or-generate, poll/events, cancel semantics, collect results and safe error mapping. Training adapters add prepare/train/checkpoint/resume/evaluate/loading compatibility as supported. Same worker protocol works locally and remotely.

Use job-scoped asset IDs and temporary directories, bounded downloads/uploads and fenced attempt tokens. Model runtimes receive controlled local staging paths, not arbitrary user paths or untrusted URLs. Object storage is the durable source across hosts. A same-host bind mount is an optimization, never a required cloud coupling.

Volume classes:
- model-cache: pinned base checkpoints/tokenizers/codecs; inference read-only after verified provisioning;
- artist-models: private versioned trained artifacts, persisted to object storage; scoped local cache;
- job-scratch: per-attempt ephemeral working data, bounded cleanup;
- database/object volumes: durable standalone deployment state;
- explicit dataset source/prepared storage, using the owner retention policy.

Models are provisioned through an explicit deployment job/administrator action before readiness. Public requests cannot trigger unbounded model downloads. Worker readiness requires validated checkpoints, compatible devices and model load/smoke evidence. Liveness does not imply generation readiness.

## Compose profiles and cloud portability

Provide one repository with per-service Dockerfiles and a Compose baseline plus profile/override files. Proposed logical profiles:
- core: API, dispatcher, PostgreSQL, Redis, storage, maintenance and CPU audio worker;
- test: explicit labeled fixture worker, never production music output;
- ace: ACE-Step generation service;
- heartmula: additional HeartMuLa runtime;
- minimax: optional SGLang-Omni runtime and two-device allocation;
- separation: Demucs;
- training: dataset preparation, ACE-Step trainer and evaluation orchestration.

Profiles select components; GPU device sets and capacity remain explicit configuration. They cannot automatically reserve distinct hardware across independent hosts. Start only required components; do not load all engines on one GPU. On one GPU, scheduler permits time-separated inference/training or exclusive mode, draining inference before training rather than oversubscribing it.

Compose is the first single-host deployment target. Cloud GPU nodes run the same worker images with backend credentials and object-storage access; database/broker/storage can become managed services. Network access uses private links/VPN or authenticated TLS, never public unauthenticated Redis or model servers. Kubernetes/provider-specific manifests are a later deployment layer; containerization alone does not guarantee provider compatibility.

Public application ingress is port 50555. Upstream 8001/8000 are internal container ports, not additional frontend endpoints. Do not expose model servers, training controls, database, Redis, storage administration or Gradio publicly. Use secrets/config mounts, exact CORS, scoped credentials, non-root users where supported, explicit resource limits and health checks. Run migration/cleanup safely across replica counts.

## Required coding-agent deliverables and tests

Deliver Dockerfiles, lockfiles, .dockerignore, secret-free environment examples, Compose/override profiles, artifact-volume documentation, image provenance/SBOM where available, migration/deployment/backup/restore runbooks and registry manifests with exact image/model revisions. No image or model weights are built/published as part of this planning task.

Prove core API on 50555 without GPU libraries; generation after model initialization; true ACE-Step adapter training and reloading; cross-profile isolation; WAV/MP3/stem validation; cold/warm startup; GPU memory/concurrency/OOM behavior; model download/resume integrity; cancellation and drain; outbox/lease recovery; persistence across container recreation; remote worker access without shared host paths; limits/secrets/health readiness; and no public auxiliary inference ports. Record GPU type/count, memory, image digest and actual test evidence. Exact supported training recipe and hardware remain validation gates.
