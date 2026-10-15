# Model integration and commercial policy

Research checked 2026-10-15. This is planning evidence, not a substitute for pinning and checking the actual downloaded release and all runtime components. Software permissiveness, model-weight licensing, training-data claims, and output rights are different questions.

## Initial candidates

| Engine | Proposed role | Published license | Initial operational status |
| --- | --- | --- | --- |
| ACE-Step 1.5 | First unrestricted-commercial adapter | MIT model card and code release | Not implemented; reverify pinned release |
| HeartMuLa | Second candidate for lyric-driven songs | Apache 2.0 code and released related weights | Disabled until adapter/license verification |
| DiffRhythm 2 | Additional full-song engine | Apache 2.0 code and weights | Disabled; review README deployment obligations too |
| YuE v1 | Optional original lyrics-to-song engine | Apache 2.0, including original v1 weights | Pin v1 explicitly; review complete pipeline |
| MiniMax Music 3 | Optional conditional-commercial adapter | MiniMax-Music3 Community License | Disabled until policy configuration and runtime validation |

Model release evidence:
- https://huggingface.co/ACE-Step/Ace-Step1.5
- https://github.com/ace-step/ACE-Step-1.5
- https://github.com/HeartMuLa/heartlib
- https://huggingface.co/HeartMuLa/HeartMuLa-oss-3B
- https://github.com/ASLP-lab/DiffRhythm2
- https://huggingface.co/ASLP-lab/DiffRhythm2
- https://huggingface.co/m-a-p/YuE-s1-7B-anneal-en-cot
- https://github.com/MiniMax-AI/MiniMax-Music3
- https://huggingface.co/MiniMaxAI/MiniMax-Music3/blob/main/LICENSE

## MiniMax Music 3 specifics

Generates complete songs up to five minutes from lyrics and musical description; documented native output is 32 kHz, 16-bit stereo WAV. The official SGLang-Omni example uses `/v1/audio/speech` with lyrics in `input`, music description in `instructions`, and `response_format=wav`. Model ID and upstream endpoint are administrator configuration, not browser-supplied values. The documented SGLang path uses two CUDA GPUs and non-streaming inference. ComfyUI has a separate supported execution path; verify its requirements independently. Do not claim a universal GPU count or VRAM minimum for all implementations.

MiniMax requires commercial product interfaces to prominently display MiniMax-Music3. Separate prior written authorization is required when aggregate annual revenue from covered products/services provided by the operator and/or affiliates exceeds USD 20 million. Hosted generators must maintain and review safeguards required by the license. The acceptable-use policy also includes disclosure obligations for machine-generated public content. Review the exact pinned license before enabling.

Return required notices to the frontend on discovery and job acceptance. Operator configuration must record policy review, review date, license revision/hash, attribution configuration and authorization reference if needed. API credentials do not establish a commercial model license. Do not describe this engine as unrestricted, royalty-free in all circumstances, or automatically eligible merely because the frontend sends a checkbox.

## Excluded from unrestricted-commercial defaults

- MusicGen official weights: CC-BY-NC 4.0. MIT inference code does not remove the weights restriction.
- YuE2: separate weights terms; personal creator monetization permission is not company-operated service permission.
- Stable Audio Open 1.0: custom community terms, requiring separate review against the no-revenue-cap requirement.

Sources: https://github.com/facebookresearch/audiocraft ; https://github.com/multimodal-art-projection/YuE ; https://huggingface.co/stabilityai/stable-audio-open-1.0

## Registry and adapter contract

Each release records: internal ID, upstream repo, exact commit/checkpoint checksums, code/weights/codec/tokenizer/dependency licenses and evidence URLs, checked date, commercial policy (`unrestricted`, `conditional`, `noncommercial`, `unknown`), license status (`verified`, `needs_review`, `not_allowed`, `user_supplied_only`), notices, enabled flag, capabilities, GPU topology and measured memory requirements. Research alone does not set `verified` for an unpinned installation.

Adapters implement capability discovery, health/readiness, request validation, deterministic input mapping, generate/submit, progress when available, cancellation semantics, safe error mapping and artifact validation. Registry capabilities are intersected with healthy worker capabilities before accepting jobs. Keep the original lyrics immutable even if an engine internally fails to sing them exactly; do not promise exact sung transcription from pass-through alone.

Never assume all models have the same HTTP API. Prefer official SDK/CLI interfaces behind isolated worker bridges. Do not call an invented endpoint for ACE-Step or treat a locally proposed bridge contract as upstream documentation. Measure cold/warm latency and peak VRAM before setting queue capacity. No automatic model download on public job requests. Do not bundle weights in public images or commit them here.


## Training and expanded capability gate

Generation compatibility does not establish trainability. None of the candidates is declared training-ready by this plan. Verify upstream training code, base/codec/dependency licenses, derivative-weight use/distribution terms, supported adapter type, recipes, dataset requirements, measured training memory, inference loading and evaluation before enabling a fine-tuning recipe.

Registry capabilities separately report `reference_conditioning`, `style_analysis`, `fine_tuning`, `singer_adaptation`, `style_adaptation`, `extension`, `section_replacement`, `remix`, `native_stems` and compatible external separation/export services. Each includes implementation status and tested constraints. Do not mark all true from a generic model-family description. Commercial fine-tuning and serving of trained derivatives require their own evidence; permissive runtime code alone is insufficient.

The actual training engine is a feasibility decision for the implementation phase. If ACE-Step or MiniMax generation works but no verified training recipe is available, the backend must report training unavailable and preserve the unmet requirement. It must not present an extracted style vector, stored prompt, or reference clip as a fine-tuned artist model.
