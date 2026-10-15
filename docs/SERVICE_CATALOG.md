# Backend capability specification

Version: 0.2-capabilities. Status: agreed service scope for planning; no implementation or feature-parity claim. Port 50555 remains the API entry point. Model-dependent services require verified adapters and cannot be advertised as available until tested.

## Separation of responsibilities

| Area | Independently hosted frontend | This backend |
| --- | --- | --- |
| Lyrics | Its own LLM connection, brainstorming, revisions, editing and approval | Immutable final-lyric ingestion, validation and provenance |
| User interface | Website, dashboard, forms, timeline, mixer, piano roll, player, administrative screens | Versioned APIs, data persistence and computation |
| Playback | Transport, local playback graph, live audition, waveform visualization | Audio delivery, range support, waveform peaks and analysis data |
| Production editing | Select regions, arrange clips, draw automation, compare takes | Validate/store edit graphs, perform requested processing and offline renders |
| Identity and billing | Login/checkout screens and frontend-side integration | Validate identity, enforce authorization/entitlements and account for work |
| Conversational control | Optional external LLM interprets user requests | Execute validated structured commands; no backend chat or lyric LLM |
| Training | Dataset/profile screens, uploads, progress and evaluation comparison | Private ingestion, preparation, training, evaluation and version activation |

Backend OpenAPI docs, CLI utilities and API examples are developer deliverables, not a bundled website. No React/Vite app, browser DAW, music player, dashboard, lyric service or checkout UI belongs in this repository. Frontend integration is demonstrated using contract tests and API examples rather than building a replacement frontend. Responsive live mixing stays in the browser or a dedicated playback client; final server renders are asynchronous.

## Service inventory

`Foundation` means required to operate safely and reliably; `Core` is the competitive first-release target; `Advanced` is planned after core. This classification does not assert that a chosen model already supports a feature.

| Service | Input | Output | Execution and permission | Stage / dependency |
| --- | --- | --- | --- | --- |
| Model discovery | Authenticated principal, optional task filter | Exact model releases, controls, license notices, health and capabilities | Synchronous; user-visible approved metadata only | Foundation |
| Asset ingestion | Authorized upload declaration and bytes | Private asset ID, checksum and validated metadata | Scoped upload; asynchronous scan/probe for large files; owner | Foundation |
| Projects and versions | Metadata, source asset IDs, edit relationships | Owner-scoped projects, immutable versions, restoration pointers | Synchronous metadata; optimistic concurrency | Core |
| Vocal song generation | Final lyrics, direction, model/profile revision, controls | Generated mix and requested exports | Asynchronous; owner quota and engine policy enforced | Core; model-dependent |
| Instrumental generation | Direction, duration/controls | Instrumental mix and requested exports | Asynchronous; verified instrumental capability | Core; model-dependent |
| Variations | Frozen source request, explicit seeds and candidate count | Separate child jobs/versions and candidate metadata | Bounded asynchronous batch; charge/reserve per candidate | Core |
| Continuation | Source version, extension start/direction and optional supplied lyrics | Extended audio plus a new version | Asynchronous; contextual extension capability | Core target; model-dependent |
| Section replacement | Source version, sample/time range, supplied replacement lyrics/direction | New assembled version; original retained | Asynchronous; source immutable; contextual editing capability | Core target; model-dependent |
| Remix / reinterpretation | Authorized reference asset, direction and preservation controls | New derivative version and provenance | Asynchronous; reference/remix capability | Core target; model-dependent |
| Vocal/accompaniment work | Authorized vocal or backing reference, required transformation | New accompaniment/vocal-conditioned audio where supported | Asynchronous; explicit adapter capability and rights record | Advanced; model-dependent |
| Artist profiles | Identity/style components, reference assets, defaults | Versioned profiles and conditioning configuration | Owner CRUD; explicit sharing only | Core; see ARTIST_TRAINING.md |
| Dataset preparation | Frozen input asset selection, labels, preparation recipe | Prepared dataset version and quality report | Asynchronous; training-specific scope and quota | Core training foundation |
| Artist training | Dataset/profile/base-model versions, recipe and budget | Checkpoint/adapter candidate and training report | Asynchronous; separate training GPU allocation | Core requirement; validated training recipe needed |
| Profile evaluation | Candidate profile version, fixed prompts, holdout set | Comparison audio, metrics and review record | Asynchronous; no automatic activation | Core training requirement |
| Stem separation | Uploaded or generated source mix, supported stem set | Aligned WAV stems, manifest and optional ZIP | Asynchronous; separation engine; owner | Core |
| Analysis | Asset ID, requested analysis types | Peaks, duration, loudness, clipping/silence flags; optional BPM/key/beat/section/lyric timing estimates | Asynchronous with cached results; owner | Core basic / Advanced estimates |
| Audio processing | Source assets plus versioned DSP recipe | Processed audio and measurements | Asynchronous; deterministic operations separately from generation | Core basic |
| Mixing render | Source assets, clip positions/trims/gains/pan and supported processing | Full mix and export job | Asynchronous; immutable render manifest; owner | Core simple / Advanced automation |
| Export | Source version, WAV/MP3/stem specification | Private downloadable output assets | Asynchronous; export spec and storage quota | Core; see OUTPUT_SPEC.md |
| Jobs and events | Job/attempt ID, cancellation/retry intent | Honest status, safe errors, progress and event replay | Owner isolation; fenced worker mutations | Foundation |
| Usage and entitlements | Verified principal and job cost reservation | Available allowance, usage entries, settlement/release | Transactional; billing provider independently configured | Foundation for paid operation |
| Webhooks | Approved destination/event subscription | Signed delivery with retry/delivery history | Server configuration, SSRF-resistant dispatch, idempotent event IDs | Advanced integration |
| Collaboration | Project/profile scope and explicit grant | Revocable ACLs, comments and share records | Owner grant; no public sharing by default | Advanced |
| Operations | Scoped admin/worker requests | Worker health, drain, allocations, registry, metrics and audit | Private internal APIs / administrator only | Foundation |
| MIDI workflows | MIDI/audio reference and supported transformation | MIDI, note estimates or conditioned generation | Asynchronous; distinct supported capability | Advanced; not required output format |

## Common operation rules

Each asynchronous request returns 202 with a durable job ID and status URL after validation and atomic persistence. Every artifact includes owner, source lineage, actual format, checksum, native/processed designation and retention class. Client-provided resource IDs must be checked for ownership, not merely existence. Freeze source versions, model revisions and validated parameters in every job.

Jobs carry `operation` and an operation-specific schema. Generation, editing, export, analysis, dataset preparation, training and evaluation share lifecycle/event infrastructure but have separate queues, budgets, timeout policies and worker capabilities. HTTP request handlers never perform inference, training or long-running rendering.

Unavailable operations return a specific capability error. Do not emulate inpainting by regenerating an entire track, call copied audio mastered, label separated stems native, or substitute reference conditioning for training. Native and separated stem availability/quality are reported separately. Where engine controls are approximate (tempo, key, lyric delivery or duration), report targets versus measurements.

## Project and session persistence

Projects group source tracks, candidates, artist versions, processing recipes and exports. Versions form an acyclic parent/derivative graph. Undo/restore selects a prior version; expensive re-generation is a distinct action. Use optimistic revisions/ETags for conflicting edits. A render always freezes an immutable session snapshot so later UI edits cannot change a running job.

Persist supported session schemas and offline renders only. Third-party VST hosting, arbitrary user-executable plugins and real-time remote audio streaming are outside the initial scope. Advanced MIDI/automation support must use explicit safe schemas and capability discovery.

## Commercial operations and acceptance

The website owns purchasing and subscription UI. Backend entitlement records are updated through authenticated server integration, with replay-resistant provider events if payment integration is later enabled. Do not assume Stripe/PayPal integration is authorized or configured. Reserve work allowance at admission and settle/release under documented outcomes; avoid duplicate deductions on retries and replay. Training has explicit maximum compute limits and never starts paid cloud resources implicitly.

Acceptance requires ownership isolation, immutable inputs, exact export behavior, recovery under worker failure, and real-model audio evidence. Maintain a fixed listening/measurement suite for lyric adherence, voice consistency, structure, editing continuity, audio defects, latency and cost. Automated scores supplement human listening; do not claim parity with Suno or others from feature names alone.

## Scope status

Confirmed: backend-only separation; external frontend LLM; port 50555; WAV and MP3 mixes; WAV stems; custom-track artist training and engine-specific capability reporting. Proposed implementation defaults: FastAPI/Postgres/Redis, ACE-Step first, conditional MiniMax adapter, seven-day generated outputs. Host/auth provider/GPU inventory, exact supported training engine and saved-output retention policy still require deployment validation. This update completes the capability planning pass; it does not authorize starting application implementation in this conversation.
