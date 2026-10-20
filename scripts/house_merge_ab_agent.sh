#!/bin/sh
# House merge/A-B agent: standalone ACE-Step LoRA merge + A/B generation node.
# It pulls trained house adapters from the hub, builds weighted merged
# checkpoints, generates a fixed prompt set for baseline and merged variants,
# then rsyncs audio, metadata, logs, and merged checkpoints back to the hub.
set -e

SSH_TARGET="${HOUSE_SSH_TARGET:?HOUSE_SSH_TARGET required}"
REMOTE_DIR="${HOUSE_REMOTE_DIR:?HOUSE_REMOTE_DIR required}"
BASE_MODEL="${HOUSE_BASE_MODEL:-acestep-v15-turbo}"
BASE_CHECKPOINT="${HOUSE_BASE_CHECKPOINT:-/opt/acestep/checkpoints/acestep-v15-turbo}"
CHECKPOINT_ROOT="${HOUSE_CHECKPOINT_ROOT:-/opt/acestep/checkpoints}"
ADAPTER_SOURCE="${HOUSE_ADAPTER_SOURCE:-/srv/oal-storage/house-lora}"
WORK="${HOUSE_WORK_DIR:-/opt/acestep/house-work}"
AB_DIR="${HOUSE_AB_DIR:-/opt/acestep/house-work/merge-ab}"
PROMPTS="${HOUSE_PROMPTS:-/opt/acestep/house-ab/prompts.json}"
MERGE_SCRIPT="${HOUSE_MERGE_SCRIPT:-/opt/acestep/house-ab/house_merge_ab.py}"
SCALES="${HOUSE_MERGE_SCALES:-0.30,0.50,0.70}"
COMBINATION_TYPE="${HOUSE_MERGE_COMBINATION_TYPE:-cat}"
PUSH_CHECKPOINTS="${HOUSE_PUSH_CHECKPOINTS:-1}"
API="http://127.0.0.1:8001"
SSH_KEY=/root/.ssh/oal_deploy
SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
SSH_RSYNC="ssh -i $SSH_KEY $SSH_OPTS"
REMOTE="$SSH_TARGET:$REMOTE_DIR"

log() { echo "[house-merge-ab-agent] $*"; }

fail() {
    echo "[house-merge-ab-agent] FAIL: $*" >&2
    mkdir -p /tmp/out
    echo "$*" > /tmp/out/FAIL
    tail -n 300 /tmp/acestep-api.log > /tmp/out/api.log 2>/dev/null || true
    rsync -aq -e "$SSH_RSYNC" /tmp/out/ "$REMOTE/" 2>/dev/null || true
    exit 1
}

start_api() {
    model="$1"
    log "starting acestep-api with model $model"
    rm -f /tmp/acestep-api.log
    (
        cd /opt/acestep
        ACESTEP_CONFIG_PATH="$model" \
        ACESTEP_INIT_LLM=false \
        ACESTEP_DEVICE=cuda:0 \
        ACESTEP_API_HOST=127.0.0.1 \
        ACESTEP_API_PORT=8001 \
        exec uv run --frozen --no-sync acestep-api
    ) > /tmp/acestep-api.log 2>&1 &
    API_PID=$!
}

stop_api() {
    if [ -n "${API_PID:-}" ]; then
        log "stopping acestep-api pid=$API_PID"
        kill "$API_PID" 2>/dev/null || true
        wait "$API_PID" 2>/dev/null || true
        API_PID=""
    fi
    pkill -f acestep-api 2>/dev/null || true
    sleep 5
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
ssh -i "$SSH_KEY" $SSH_OPTS "$SSH_TARGET" "mkdir -p $REMOTE_DIR/merged $REMOTE_DIR/audio"
mkdir -p "$WORK/adapters" "$AB_DIR/audio" "$AB_DIR/checkpoints"

# --- pull trained adapters ----------------------------------------------------
log "pulling adapters from $SSH_TARGET:$ADAPTER_SOURCE"
rsync -aq --partial --timeout=300 -e "$SSH_RSYNC" \
    "$SSH_TARGET:$ADAPTER_SOURCE/" "$WORK/adapters/" || fail "adapter pull failed"

# --- merge --------------------------------------------------------------------
log "building merged checkpoints"
/opt/acestep/.venv/bin/python "$MERGE_SCRIPT" merge \
    --base-checkpoint "$BASE_CHECKPOINT" \
    --adapter-root "$WORK/adapters" \
    --checkpoint-root "$CHECKPOINT_ROOT" \
    --variant-prefix house_ \
    --scales "$SCALES" \
    --combination-type "$COMBINATION_TYPE" || fail "merge failed"

# Validate merged checkpoints locally. Pushing them is deferred until after
# audio so review files arrive first even when node upload bandwidth is slow.
for scale in $(printf '%s' "$SCALES" | tr ',' ' '); do
    suffix=$(printf '%03d' "$(awk -v s="$scale" 'BEGIN { printf "%d", s * 100 + 0.5 }')")
    model="acestep-v15-house_${suffix}"
    [ -d "$CHECKPOINT_ROOT/$model" ] || fail "missing merged checkpoint $model"
done

# --- generate A/B clips -------------------------------------------------------
rm -f "$AB_DIR/metadata.json"
touch "$AB_DIR/metadata.json"
printf '[]' > "$AB_DIR/metadata.json"

generate_model() {
    model="$1"
    variant="$2"
    start_api "$model"
    /opt/acestep/.venv/bin/python "$MERGE_SCRIPT" generate \
        --api "$API" \
        --model "$model" \
        --variant "$variant" \
        --prompts "$PROMPTS" \
        --output-dir "$AB_DIR/audio" \
        --metadata "$AB_DIR/metadata.json" || {
            tail -n 300 /tmp/acestep-api.log || true
            fail "generation failed for $model"
        }
    stop_api
}

generate_model "$BASE_MODEL" "baseline_turbo"
for scale in $(printf '%s' "$SCALES" | tr ',' ' '); do
    suffix=$(printf '%03d' "$(awk -v s="$scale" 'BEGIN { printf "%d", s * 100 + 0.5 }')")
    generate_model "acestep-v15-house_${suffix}" "house_${suffix}"
done

# --- push results -------------------------------------------------------------
log "pushing audio and metadata"
rsync -aq --partial --timeout=600 -e "$SSH_RSYNC" "$AB_DIR/audio/" "$REMOTE/audio/" || fail "audio push failed"
rsync -aq -e "$SSH_RSYNC" "$AB_DIR/metadata.json" "$REMOTE/metadata.json" || fail "metadata push failed"

if [ "$PUSH_CHECKPOINTS" = "1" ]; then
    for scale in $(printf '%s' "$SCALES" | tr ',' ' '); do
        suffix=$(printf '%03d' "$(awk -v s="$scale" 'BEGIN { printf "%d", s * 100 + 0.5 }')")
        model="acestep-v15-house_${suffix}"
        variant="house_${suffix}"
        log "pushing merged checkpoint $model"
        rsync -aq --partial --timeout=1800 -e "$SSH_RSYNC" \
            "$CHECKPOINT_ROOT/$model/" "$REMOTE/merged/$variant/" || fail "checkpoint push failed"
    done
fi

mkdir -p /tmp/out
tail -n 300 /tmp/acestep-api.log > /tmp/out/api.log 2>/dev/null || true
rsync -aq -e "$SSH_RSYNC" /tmp/out/api.log "$REMOTE/api.log" || true
touch /tmp/DONE
rsync -aq -e "$SSH_RSYNC" /tmp/DONE "$REMOTE/DONE" || fail "DONE marker push failed"
log "DONE"
