#!/bin/sh
# House training agent: standalone ACE-Step LoRA trainer node. No OAL queue,
# DB, or code bundle. Pulls the tensor tar from the hub over ssh, drives the
# baked acestep-api through /v1/training/*, and rsyncs the PEFT adapter plus
# status markers back to the hub. The hub-side runner (scripts/house_train.py)
# only watches those marker files.
set -e

MODEL="${HOUSE_MODEL:-acestep-v15-turbo}"
RUN_ID="${HOUSE_RUN_ID:-house-run}"
SSH_TARGET="${HOUSE_SSH_TARGET:?HOUSE_SSH_TARGET required}"
REMOTE_DIR="${HOUSE_REMOTE_DIR:?HOUSE_REMOTE_DIR required}"
TENSOR_TAR="${HOUSE_TENSOR_TAR:?HOUSE_TENSOR_TAR required}"
WORK="${HOUSE_WORK_DIR:-/opt/acestep/house-work}"
API="http://127.0.0.1:8001"
EPOCHS="${HOUSE_EPOCHS:-20}"
RANK="${HOUSE_RANK:-64}"
ALPHA="${HOUSE_ALPHA:-128}"
LR="${HOUSE_LR:-1e-4}"
SEED="${HOUSE_SEED:-42}"
BATCH="${HOUSE_BATCH_SIZE:-1}"
GRAD_ACCUM="${HOUSE_GRAD_ACCUM:-4}"
SAVE_EVERY="${HOUSE_SAVE_EVERY:-5}"
GRAD_CKPT="${HOUSE_GRAD_CKPT:-0}"
POLL="${HOUSE_POLL_SECONDS:-60}"
MAX_HOURS="${HOUSE_MAX_HOURS:-24}"

SSH_KEY=/root/.ssh/oal_deploy
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
SSH_RSYNC="ssh -i $SSH_KEY $SSH_OPTS"
REMOTE="$SSH_TARGET:$REMOTE_DIR"

log() { echo "[house-agent] $*"; }

fail() {
    echo "[house-agent] FAIL: $*" >&2
    mkdir -p /tmp/out
    echo "$*" > /tmp/out/FAIL
    tail -n 200 /tmp/acestep-api.log > /tmp/out/api.log 2>/dev/null || true
    rsync -aq -e "$SSH_RSYNC" /tmp/out/ "$REMOTE/" 2>/dev/null || true
    exit 1
}

# --- ssh key for hub push/pull ------------------------------------------------
mkdir -p /root/.ssh
if [ -n "${OAL_PUSH_PRIVKEY_B64:-}" ]; then
    printf '%s' "$OAL_PUSH_PRIVKEY_B64" | base64 -d > "$SSH_KEY"
    chmod 600 "$SSH_KEY"
fi
i=0
until ssh -i "$SSH_KEY" $SSH_OPTS -o ConnectTimeout=10 "$SSH_TARGET" true; do
    i=$((i + 1))
    [ "$i" -ge 30 ] && fail "hub ssh unreachable"
    sleep 5
done
ssh -i "$SSH_KEY" $SSH_OPTS "$SSH_TARGET" "mkdir -p $REMOTE_DIR"
mkdir -p "$WORK"

# --- engine: start with the chosen model (checkpoints are baked) --------------
export ACESTEP_CONFIG_PATH="$MODEL"
export ACESTEP_INIT_LLM=false ACESTEP_DEVICE=cuda:0
export ACESTEP_API_HOST=0.0.0.0 ACESTEP_API_PORT=8001
log "starting acestep-api with model $MODEL"
( cd /opt/acestep && exec uv run --frozen --no-sync acestep-api ) > /tmp/acestep-api.log 2>&1 &

# --- tensors: pull while the engine loads -------------------------------------
log "pulling tensors"
rsync -aq --partial --timeout=180 -e "$SSH_RSYNC" "$SSH_TARGET:$TENSOR_TAR" "$WORK/" \
    || fail "tensor pull failed"
log "extracting tensors"
zstd -dc "$WORK/$(basename "$TENSOR_TAR")" | tar -xf - -C "$WORK" \
    || fail "tensor extract failed"
rm -f "$WORK/$(basename "$TENSOR_TAR")"
TENSOR_DIR="$WORK/tensors"
[ -d "$TENSOR_DIR" ] || fail "tensors dir missing after extract"

i=0
until curl -fsS "$API/health" >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -ge 240 ] && fail "engine not ready"
    sleep 5
done
log "engine ready"

# The engine lazy-loads models; training needs the decoder initialized.
log "initializing model $MODEL"
curl -fsS -X POST "$API/v1/init" -H 'Content-Type: application/json' \
    -d "{\"model\":\"$MODEL\"}" > /tmp/init-resp.json || fail "model init failed"
log "init resp: $(head -c 200 /tmp/init-resp.json)"
grep -q '"error":null' /tmp/init-resp.json || fail "model init rejected: $(head -c 200 /tmp/init-resp.json)"

# --- training ------------------------------------------------------------------
GC=true
[ "$GRAD_CKPT" = "0" ] && GC=false
cat > /tmp/start.json <<JSON
{"tensor_dir":"$TENSOR_DIR","lora_output_dir":"$WORK/lora","train_epochs":$EPOCHS,"train_batch_size":$BATCH,"gradient_accumulation":$GRAD_ACCUM,"save_every_n_epochs":$SAVE_EVERY,"lora_rank":$RANK,"lora_alpha":$ALPHA,"learning_rate":$LR,"training_seed":$SEED,"gradient_checkpointing":$GC}
JSON
log "start: $(cat /tmp/start.json)"
curl -fsS -X POST "$API/v1/training/start" -H 'Content-Type: application/json' \
    -d @/tmp/start.json > /tmp/start-resp.json || fail "training start failed"
log "start resp: $(cat /tmp/start-resp.json)"
grep -q '"error":null' /tmp/start-resp.json || fail "training start rejected: $(head -c 200 /tmp/start-resp.json)"

START=$(date +%s)
WALL=$((MAX_HOURS * 3600))
while :; do
    sleep "$POLL"
    curl -s "$API/v1/training/status" -o /tmp/status.json || true
    rsync -aq -e "$SSH_RSYNC" /tmp/status.json "$REMOTE/status.json" 2>/dev/null || true
    STATE=$(python3 - <<'PY'
import json
try:
    d = json.load(open("/tmp/status.json"))["data"] or {}
except Exception:
    print("WAIT -"); raise SystemExit
if d.get("error"):
    print("ERROR " + str(d["error"])[:200].replace("\n", " "))
elif not d.get("is_training"):
    print("DONE -")
else:
    print(f"RUN ep{d.get('current_epoch')} loss={d.get('current_loss')}")
PY
)
    log "state: $STATE"
    case "$STATE" in
        DONE*) break ;;
        ERROR*) fail "training error: ${STATE#ERROR }" ;;
    esac
    [ $(( $(date +%s) - START )) -gt "$WALL" ] && fail "wall clock exceeded ${MAX_HOURS}h"
done

# --- export + push back ----------------------------------------------------------
log "exporting adapter"
curl -fsS -X POST "$API/v1/training/export" -H 'Content-Type: application/json' \
    -d "{\"lora_output_dir\":\"$WORK/lora\",\"export_path\":\"$WORK/export\"}" \
    > /tmp/export-resp.json || fail "export failed"
log "export resp: $(cat /tmp/export-resp.json)"
grep -q '"error":null' /tmp/export-resp.json || fail "export rejected: $(head -c 200 /tmp/export-resp.json)"
# The engine copytree's lora/final -> export, and final holds an adapter/ subdir,
# so the adapter lands at export/adapter/; locate it robustly.
ADAPTER_DIR="$WORK/export/adapter"
[ -f "$ADAPTER_DIR/adapter_config.json" ] || ADAPTER_DIR="$WORK/export"
if [ ! -f "$ADAPTER_DIR/adapter_config.json" ]; then
    FOUND="$(find "$WORK/export" -name adapter_config.json 2>/dev/null | head -1)"
    [ -n "$FOUND" ] && ADAPTER_DIR="$(dirname "$FOUND")"
fi
[ -f "$ADAPTER_DIR/adapter_config.json" ] || fail "export missing adapter_config.json"
log "adapter located at $ADAPTER_DIR"
rsync -aq -e "$SSH_RSYNC" "$ADAPTER_DIR/" "$REMOTE/adapter/" || fail "adapter push failed"
# Push the epoch checkpoint ladder (each epoch_*/ holds adapter/ + optimizer state).
if [ -d "$WORK/lora/checkpoints" ]; then
    rsync -aq -e "$SSH_RSYNC" "$WORK/lora/checkpoints/" "$REMOTE/checkpoints/" \
        || log "checkpoints push failed (non-fatal)"
fi
rsync -aq -e "$SSH_RSYNC" /tmp/status.json "$REMOTE/status.json" || true
mkdir -p /tmp/out
tail -n 200 /tmp/acestep-api.log > /tmp/out/api.log 2>/dev/null || true
rsync -aq -e "$SSH_RSYNC" /tmp/out/api.log "$REMOTE/api.log" || true
touch /tmp/DONE
rsync -aq -e "$SSH_RSYNC" /tmp/DONE "$REMOTE/DONE" || fail "DONE marker push failed"
log "DONE"
