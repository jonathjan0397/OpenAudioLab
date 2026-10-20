# House LoRA Training and Model Merge

This document describes the full house-LoRA workflow:

1. curate per-genre training sets from the local music archive,
2. preprocess audio into ACE-Step tensors,
3. train PEFT LoRAs against ACE-Step Turbo on rented Vast nodes,
4. merge the trained genre LoRAs into standalone ACE-Step checkpoints,
5. generate fixed A/B clips for owner review,
6. retain every trained and merged version for later promotion or rollback.

## 1. High-Level Architecture

The house-LoRA pipeline is intentionally separate from the normal OAL queue.

```text
local curation
  -> per-family dataset JSON
  -> ACE-Step tensor preprocessing
  -> tensor tar on hub
  -> Vast training node
  -> PEFT adapter pushed back to hub
  -> optional merge/A-B Vast node
  -> merged ACE-Step checkpoint + A/B audio pushed back to hub
  -> rsync to local Cold-Archive review folder
```

Key components:

- `scripts/select_family.py`: selects balanced tracks per genre family.
- `curation/selection_perfamily/run_preprocess.py`: ACE-Step preprocessing runner.
- `scripts/house_train.py`: hub-side runner that rents a Vast training node and
  watches marker files.
- `stratastack/acestep-train` image: contains ACE-Step, the baked base
  checkpoints, and the node-side `house-agent.sh`.
- `scripts/house_merge_ab.py`: offline LoRA merge and A/B generation helper.
- `scripts/house_merge_ab_agent.sh`: node-side merge/A-B agent.
- `Dockerfile.house_merge`: small layer over the training image containing the
  merge/A-B agent and prompt files.

## 2. Curation Inputs

The local curation source is:

`/Cold-Archive/OpenAudioLab/curation/tracks.jsonl`

At the time of the house-v1 run this contained `81,170` candidate track records.
The selector normalizes messy genre strings into 13 families:

- `blues`
- `country`
- `electronic`
- `folk`
- `gospel`
- `hiphop`
- `jazz`
- `metal`
- `pop`
- `punk_alt`
- `rnb_soul`
- `rock`
- `score`

Selector behavior:

- first-match-wins genre mapping, ordered from specific to general,
- target about `200` tracks per family,
- file size filter: `2.5 MB` to `25 MB`,
- decade round-robin balancing,
- per-artist cap relaxed in passes: `3`, `6`, `12`, then unlimited,
- dedupe by audio path,
- writes:
  - `curation/selection_perfamily/<family>.jsonl`
  - `curation/selection_perfamily/<family>_dataset.json`

The dataset JSON is in ACE-Step preprocess format. Each sample is labeled as
instrumental:

```json
{
  "audio_path": "...",
  "filename": "...",
  "caption": "artist, family, decade",
  "lyrics": "[Instrumental]",
  "genre": "family",
  "is_instrumental": true,
  "labeled": true
}
```

Actual selected counts:

| Family | Tracks selected |
|---|---:|
| blues | 200 |
| country | 200 |
| electronic | 200 |
| folk | 153 |
| gospel | 83 |
| hiphop | 200 |
| jazz | 162 |
| metal | 177 |
| pop | 200 |
| punk_alt | 200 |
| rnb_soul | 200 |
| rock | 200 |
| score | 119 |

## 3. Tensor Preprocessing

Preprocessing converts selected audio into ACE-Step training tensors.

Runner:

`curation/selection_perfamily/run_preprocess.py`

It calls:

```python
from acestep.training_v2.preprocess import preprocess_audio_files

preprocess_audio_files(
    audio_dir=None,
    output_dir=os.environ.get("OUT", "/work/tensors_rock"),
    checkpoint_dir=os.environ.get("CKPT", "/opt/acestep/checkpoints"),
    variant=os.environ.get("VARIANT", "turbo"),
    max_duration=float(os.environ.get("MAXDUR", "240")),
    dataset_json=os.environ.get("DJ", "/work/rock_dataset.json"),
    device="cuda:0",
)
```

Outputs are tarred with zstd and stored on the hub under:

`/srv/oal-storage/house-lora/tensors-<family>.tar.zst`

Examples:

- `/srv/oal-storage/house-lora/tensors-pop.tar.zst`
- `/srv/oal-storage/house-lora/tensors-rnb_soul.tar.zst`
- `/srv/oal-storage/house-lora/tensors-score.tar.zst`

## 4. Training Node Model

Training uses a standalone Vast node, not the OAL queue.

Hub-side runner:

`scripts/house_train.py`

Node-side agent:

`/usr/local/bin/house-agent.sh` inside `stratastack/acestep-train`.

The hub runner:

1. searches Vast offers,
2. ranks offers by estimated total cost,
3. creates a Vast instance with the training image,
4. watches hub-side marker files written by the node,
5. destroys the node after success or failure.

Offer ranking filters:

- `gpu_ram >= 24 GB`,
- one GPU,
- rentable,
- CUDA `>= 12.8`,
- verified host,
- North America only,
- reliability `>= 0.95`,
- default max cost `<= $0.40/hr`,
- enough disk,
- cooldown list for recently failed offers.

Estimated cost includes:

- image pull,
- tensor pull,
- training time,
- fixed boot/export/rsync overhead.

## 5. Training Agent Flow

The node-side agent performs the actual training.

Flow:

1. Wait for hub SSH reachability.
2. Create the remote marker directory.
3. Pull the family tensor tar from the hub.
4. Extract tensors into the node work directory.
5. Start `acestep-api` with the selected base model.
6. Initialize the DiT model through `/v1/init`.
7. Start training through `/v1/training/start`.
8. Poll `/v1/training/status`.
9. Push `status.json` back to the hub periodically.
10. Export the adapter through `/v1/training/export`.
11. Push the final adapter directory back to the hub.
12. Push checkpoint ladder directories back to the hub.
13. Push `api.log`, `DONE`, or `FAIL`.

Marker files on the hub:

```text
/srv/oal-storage/house-lora/<run-id>/
  DONE
  FAIL
  status.json
  api.log
  adapter/
  checkpoints/
```

## 6. Actual House-v1 Training Settings

The successful house-v1 adapters used:

- base model: `acestep-v15-turbo`
- PEFT type: `LORA`
- rank: `64`
- alpha: `128`
- target modules:
  - `q_proj`
  - `k_proj`
  - `v_proj`
  - `o_proj`
- epochs: `15`
- checkpoint ladder saved every `5` epochs
- learning rate: `1e-4`
- seed: `42`
- batch size: `1`
- gradient accumulation: `4`
- gradient checkpointing: disabled for Turbo

Each successful adapter is approximately:

`176,210,656 bytes`

Final checkpoint losses are encoded in checkpoint directory names. The final
epoch-15 losses ranged from:

- best: `0.1942` for `jazz`
- highest: `0.2158` for `hiphop`

Final epoch-15 losses:

| Family | Final epoch-15 loss |
|---|---:|
| blues | 0.2043 |
| country | 0.2102 |
| electronic | 0.1967 |
| folk | 0.2036 |
| gospel | 0.2082 |
| hiphop | 0.2158 |
| jazz | 0.1942 |
| metal | 0.2038 |
| pop | 0.2034 |
| punk_alt | 0.2013 |
| rnb_soul | 0.2104 |
| rock | 0.2034 |
| score | 0.1987 |

`house-v1-turbo` was attempted but did not produce a usable adapter and is not
included in the merge A/B.

## 7. Training Commands

List candidate offers:

```bash
HOUSE_TENSOR_TAR=/srv/oal-storage/house-lora/tensors-pop.tar.zst \
scripts/house_train.py offers --model turbo --epochs 15
```

Run one family:

```bash
HOUSE_TENSOR_TAR=/srv/oal-storage/house-lora/tensors-pop.tar.zst \
scripts/house_train.py run \
  --model turbo \
  --run-id house-v1-pop \
  --epochs 15 \
  --rank 64 \
  --alpha 128 \
  --lr 1e-4 \
  --seed 42 \
  --wall-hours 24 \
  --max-attempts 3
```

The runner writes the adapter to:

`/srv/oal-storage/house-lora/house-v1-pop/adapter`

## 8. ACE-Step LoRA Runtime Semantics

ACE-Step applies LoRAs at runtime through PEFT adapters on `model.decoder`.

Important source behavior:

- `acestep/core/generation/handler/lora/lifecycle.py`
  - loads adapters with `PeftModel.from_pretrained(...)` or
    `decoder.load_adapter(...)`,
  - tracks loaded adapters in a handler registry,
  - sets the active adapter with `decoder.set_adapter(...)`.
- `acestep/core/generation/handler/lora/controls.py`
  - exposes LoRA scale as a `0.0` to `1.0` multiplier,
  - applies scale to the active adapter.
- `acestep/core/lora/scaling.py`
  - multiplies the adapter's base PEFT scaling value by the requested scale.
- `acestep/training/lora_utils.py`
  - `merge_lora_weights(model)` simply calls
    `model.decoder.merge_and_unload()`.

ACE-Step does not provide an HTTP merge endpoint. It also does not define an
official multi-LoRA merge procedure. Multi-LoRA merging is therefore a custom
operation.

## 9. Merge Inputs

The merge process uses:

- base checkpoint:
  - `/opt/acestep/checkpoints/acestep-v15-turbo`
- trained adapters:
  - `/srv/oal-storage/house-lora/house-v1-*/adapter`
- merge script:
  - `scripts/house_merge_ab.py`
- merge agent:
  - `scripts/house_merge_ab_agent.sh`
- merge image:
  - `stratastack/acestep-train:v5-house-ab`

For the corrected full A/B, the hub-side adapter source was:

`/srv/oal-storage/house-lora/merge-adapters`

That directory contains only the 13 successful adapters in the layout expected
by the merge script:

```text
merge-adapters/
  house-v1-blues/adapter/
  house-v1-country/adapter/
  ...
  house-v1-score/adapter/
```

## 10. First Merge Attempt and Failure

The first full merge used PEFT weighted merging with:

```python
add_weighted_adapter(
    names,
    [scale] * len(names),
    "house",
    combination_type="linear",
)
```

For 13 adapters, this meant:

- scale `0.30` became roughly `3.9x` total LoRA strength,
- scale `0.50` became roughly `6.5x` total LoRA strength,
- scale `0.70` became roughly `9.1x` total LoRA strength.

The merged audio was unrecognizable as music.

First run paths:

- Hub: `/srv/oal-storage/house-lora/merge-ab-2026-10-19`
- Local: `/Cold-Archive/OpenAudioLab/house-lora-ab/2026-10-19`

## 11. Corrected Merge Method

The corrected merge uses:

```python
weights = [scale / len(adapters) for _ in adapters]

add_weighted_adapter(
    names,
    weights,
    "house",
    combination_type="cat",
)

merge_and_unload(
    safe_merge=True,
    adapter_names=["house"],
)
```

This changes the meaning of scale:

- `0.30` means total merge strength `0.30`,
- each of the 13 genre LoRAs contributes `0.30 / 13`,
- `0.50` and `0.70` are also total strengths.

Why `cat` was chosen:

- `cat` concatenates adapter components and preserves the weighted sum of LoRA
  deltas more directly.
- `linear` sums A and B separately, which can introduce cross terms when many
  adapters are merged.

Why normalization was required:

- ACE-Step runtime LoRA scale is a single 0–1 multiplier for the active adapter.
- A merged checkpoint should approximate that runtime scale, not multiply it by
  the number of adapters.

## 12. Merge Script Details

`scripts/house_merge_ab.py` has two subcommands.

### Merge

```bash
python scripts/house_merge_ab.py merge \
  --base-checkpoint /opt/acestep/checkpoints/acestep-v15-turbo \
  --adapter-root /opt/acestep/house-work/adapters \
  --checkpoint-root /opt/acestep/checkpoints \
  --variant-prefix house_ \
  --scales 0.30,0.50,0.70 \
  --combination-type cat
```

For each scale it:

1. loads the base ACE-Step model,
2. wraps `model.decoder` with PEFT,
3. loads every discovered adapter,
4. creates a combined adapter named `house`,
5. merges only the `house` adapter,
6. assigns the merged decoder back to `model.decoder`,
7. saves a full checkpoint,
8. copies auxiliary files from the base checkpoint.

Auxiliary files copied include:

- `configuration_acestep_v15.py`
- `modeling_acestep_v15_turbo.py`
- `silence_latent.pt`

The saved checkpoint names are:

- `acestep-v15-house_030`
- `acestep-v15-house_050`
- `acestep-v15-house_070`

### Generate

```bash
python scripts/house_merge_ab.py generate \
  --api http://127.0.0.1:8001 \
  --model acestep-v15-house_030 \
  --variant house_030 \
  --prompts /opt/acestep/house-ab/prompts.json \
  --output-dir /opt/acestep/house-work/merge-ab/audio \
  --metadata /opt/acestep/house-work/merge-ab/metadata.json
```

Generation uses the ACE-Step HTTP API:

- `/health`
- `/v1/init`
- `/release_task`
- `/query_result`
- `/v1/audio?path=...`

The agent starts a fresh API process for each checkpoint to avoid model-switch
state issues.

## 13. A/B Prompt Set

Full prompt file:

`curation/house_ab_prompts.json`

Sanity prompt file:

`curation/house_ab_prompts_test.json`

Full A/B settings:

- 13 genre prompts,
- 3 neutral prompts,
- duration: `30` seconds,
- seed: `42`,
- instrumental: `true`,
- batch size: `1`,
- thinking: `false`,
- format: WAV.

The neutral prompts are:

- `neutral_summer`
- `neutral_midnight`
- `neutral_neon`

## 14. Merge Agent Flow

`scripts/house_merge_ab_agent.sh` runs inside the Vast node.

Flow:

1. Wait for hub SSH.
2. Create remote `audio/` and `merged/` directories.
3. Pull adapters from `HOUSE_ADAPTER_SOURCE`.
4. Run `house_merge_ab.py merge`.
5. Validate that merged checkpoints exist locally.
6. Start ACE-Step API for baseline Turbo and generate the prompt set.
7. Start ACE-Step API for each merged checkpoint and generate the prompt set.
8. Push audio and metadata to the hub.
9. Optionally push merged checkpoints to the hub.
10. Push `api.log` and `DONE`.

Important environment variables:

- `HOUSE_SSH_TARGET`
- `HOUSE_REMOTE_DIR`
- `HOUSE_ADAPTER_SOURCE`
- `HOUSE_PROMPTS`
- `HOUSE_MERGE_SCALES`
- `HOUSE_MERGE_COMBINATION_TYPE`
- `HOUSE_PUSH_CHECKPOINTS`
- `OAL_PUSH_PRIVKEY_B64`

Operational lesson: node-to-hub upload can be much slower than hub-to-node
download. The agent therefore pushes audio and metadata before large merged
checkpoints.

## 15. Sanity Test

A one-adapter sanity merge was run before the corrected full A/B.

Settings:

- adapter: `house-v1-pop`
- scale: `0.30`
- combination: `cat`
- normalized weights: enabled
- prompts: 2 test prompts
- Vast contract: `56826462`

Paths:

- Hub: `/srv/oal-storage/house-lora/merge-ab-one2-2026-10-19`
- Local: `/Cold-Archive/OpenAudioLab/house-lora-ab/2026-10-19-one-pop`
- Review page: `index.html`

## 16. Corrected Full A/B

The corrected full A/B used all 13 house LoRAs.

Settings:

- scales: `0.30`, `0.50`, `0.70`
- combination: `cat`
- normalized weights: enabled
- full prompt set: 16 prompts
- Vast contract: `56827635`

Paths:

- Hub: `/srv/oal-storage/house-lora/merge-ab-v2-2026-10-19`
- Local: `/Cold-Archive/OpenAudioLab/house-lora-ab/2026-10-19-v2`
- Review page: `index.html`

Local corrected A/B layout:

```text
/Cold-Archive/OpenAudioLab/house-lora-ab/2026-10-19-v2/
  audio/
    baseline_turbo/
    house_030/
    house_050/
    house_070/
  merged/
    house_030/
    house_050/
    house_070/
  metadata.json
  index.html
```

## 17. Retention Policy

All trained and merged versions are retained.

Trained adapters:

`/srv/oal-storage/house-lora/house-v1-*/adapter`

First bad A/B:

- Hub: `/srv/oal-storage/house-lora/merge-ab-2026-10-19`
- Local: `/Cold-Archive/OpenAudioLab/house-lora-ab/2026-10-19`

One-adapter sanity:

- Hub: `/srv/oal-storage/house-lora/merge-ab-one2-2026-10-19`
- Local: `/Cold-Archive/OpenAudioLab/house-lora-ab/2026-10-19-one-pop`

Corrected full A/B:

- Hub: `/srv/oal-storage/house-lora/merge-ab-v2-2026-10-19`
- Local: `/Cold-Archive/OpenAudioLab/house-lora-ab/2026-10-19-v2`

The original `acestep-v15-turbo` checkpoint remains available for rollback.

## 18. Promotion Plan

No merged model has been promoted yet.

If a merged variant is selected:

1. Copy the winning merged checkpoint to a stable name such as:

   `acestep-v15-house-turbo`

2. Deploy workers with:

   ```bash
   ACESTEP_CONFIG_PATH=acestep-v15-house-turbo
   OAL_ACESTEP_MODEL=acestep-v15-house-turbo
   ```

3. Keep `acestep-v15-turbo` as the rollback default.

## 19. Known Pitfalls

- Raw per-adapter weights across many LoRAs multiply total merge strength.
- `linear` combination can introduce cross terms for many adapters.
- ACE-Step runtime scale is 0–1 for the active adapter; merged checkpoints need
  equivalent total strength.
- Node-to-hub checkpoint upload can be slow; push audio first.
- Remote marker directories must exist before rsync writes into subdirectories.
- Vast may restart a failed entrypoint; clean stale `DONE`/`FAIL` markers before
  rerunning.
- Disk size affects Vast total hourly cost. For the merge A/B, `80 GB` disk kept
  the RTX 3090 node under `$0.30/hr` total.
