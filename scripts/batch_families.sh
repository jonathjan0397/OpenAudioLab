#!/usr/bin/env bash
# Batch driver: for each family, ensure tensors on the hub, (re)create the warm
# Vast node, wait for the agent's DONE marker, then collect to NAS + OAL.
# Families already having tensors-<f>.tar.zst on the hub skip preprocessing.
set -uo pipefail

OFFER=54752898
IMAGE=stratastack/acestep-train:v2
DISK=120
HUB=administrator@192.151.156.124
HUBPW='3671A113a05786!'
HUBST=/srv/oal-storage/house-lora
SP=/Cold-Archive/OpenAudioLab/curation/selection_perfamily
CIDF=/tmp/house_cid
SSH="sshpass -p $HUBPW ssh -o StrictHostKeyChecking=no"
log(){ echo "[$(date +%H:%M:%S)] $*"; }

hub_vast(){ $SSH "$HUB" "export VAST_API_KEY=\$(grep -E '^OAL_VAST_API_KEY=' ~/oal-backend/.env.backend | cut -d= -f2-); $*"; }

preprocess(){  # $1=family
    local f="$1" rc=0
    log "preprocess $f"
    rm -rf "$SP/tensors_${f}" "$SP/tensors-${f}.tar.zst"
    sudo -n docker run --rm --gpus device=0 -v /mnt/truenas:/mnt/truenas:ro -v "$SP":/work \
        -e DJ=/work/${f}_dataset.json -e OUT=/work/tensors_${f} --entrypoint sh house-train:ep5 \
        -c "cd /opt/acestep && (apt-get update -qq && apt-get install -y -qq ffmpeg >/dev/null 2>&1 || true) && uv run --frozen --no-sync python /work/run_preprocess.py" \
        > "$SP/preproc_${f}.log" 2>&1 || rc=$?
    if [ "$rc" -ne 0 ] || ! grep -q PREPROCESS_RESULT "$SP/preproc_${f}.log"; then
        log "preprocess $f FAILED (rc=$rc)"
        rm -f "$SP/tensors-${f}.tar.zst"
        return 1
    fi
    ( cd "$SP" && tar --transform "s,^tensors_${f},tensors," -cf - tensors_${f} | zstd -q -T0 -f -o "tensors-${f}.tar.zst" ) || return 1
    sshpass -p "$HUBPW" rsync -a -e "ssh -o StrictHostKeyChecking=no" "$SP/tensors-${f}.tar.zst" "$HUB:$HUBST/" || return 1
    log "preprocess $f done: $(grep PREPROCESS_RESULT "$SP/preproc_${f}.log" | tail -1)"
}

for f in "$@"; do
    RUN="house-v1-${f}"
    log "==== $f ===="
    if ! $SSH "$HUB" "test -f $HUBST/tensors-${f}.tar.zst"; then
        preprocess "$f" || { log "SKIP $f (preprocess failed)"; continue; }
    else
        log "tensors present, skipping preprocess"
    fi

    # destroy previous instance (keep one at a time, same warm host)
    if [ -f "$CIDF" ]; then
        old=$(cat "$CIDF"); [ -n "$old" ] && hub_vast "$HOME/OpenAudioLab/.venv/bin/vastai destroy instance $old -y >/dev/null 2>&1"
    fi

    # clear stale markers so a new run is not judged by the previous attempt
    $SSH "$HUB" "rm -f $HUBST/$RUN/DONE $HUBST/$RUN/FAIL $HUBST/$RUN/status.json" >/dev/null 2>&1 || true

    # create new instance for this family (env built on the hub; key read there)
    raw=$($SSH "$HUB" bash -s "$f" "$RUN" "$HUBST" "$OFFER" "$IMAGE" "$DISK" <<'REMOTE'
set -e
f="$1"; run="$2"; hubst="$3"; offer="$4"; image="$5"; disk="$6"
export VAST_API_KEY=$(grep -E '^OAL_VAST_API_KEY=' ~/oal-backend/.env.backend | cut -d= -f2-)
KEY=$(grep -E '^OAL_PUSH_PRIVKEY_B64=' ~/oal-backend/.env.backend | cut -d= -f2-)
ENV="-e HOUSE_MODEL=acestep-v15-turbo -e HOUSE_RUN_ID=$run -e HOUSE_SSH_TARGET=administrator@192.151.156.124 -e HOUSE_REMOTE_DIR=$hubst/$run -e HOUSE_TENSOR_TAR=$hubst/tensors-$f.tar.zst -e HOUSE_EPOCHS=15 -e HOUSE_RANK=64 -e HOUSE_ALPHA=128 -e HOUSE_LR=1e-4 -e HOUSE_SEED=42 -e HOUSE_BATCH_SIZE=1 -e HOUSE_GRAD_ACCUM=4 -e HOUSE_SAVE_EVERY=5 -e HOUSE_GRAD_CKPT=0 -e HOUSE_MAX_HOURS=6 -e HOUSE_POLL_SECONDS=60 -e OAL_PUSH_PRIVKEY_B64=$KEY"
~/OpenAudioLab/.venv/bin/vastai --raw create instance "$offer" --image "$image" --disk "$disk" --label "house-$f" --env "$ENV" --args run
REMOTE
)
    CID=$(echo "$raw" | grep -oE '"new_contract": [0-9]+' | grep -oE '[0-9]+' | head -1)
    echo "${CID:-}" > "$CIDF"
    log "created instance ${CID:-NONE} for $f"
    [ -z "$CID" ] && { log "SKIP $f (create failed)"; continue; }

    # wait for DONE/FAIL (up to ~3h)
    status=""
    for i in $(seq 1 180); do
        sleep 60
        r=$($SSH "$HUB" "if [ -f $HUBST/$RUN/DONE ]; then echo DONE; elif [ -f $HUBST/$RUN/FAIL ]; then echo FAIL:\$(cat $HUBST/$RUN/FAIL); else python3 -c \"import json;d=json.load(open('$HUBST/$RUN/status.json')).get('data') or {};print('ep'+str(d.get('current_epoch')))\" 2>/dev/null || echo loading; fi" 2>/dev/null)
        log "$f: $r"
        case "$r" in
            DONE*) status=DONE; break ;;
            FAIL*) status=FAIL; break ;;
        esac
    done
    [ "$status" != DONE ] && { log "NOT DONE ($status) for $f — leaving instance, continuing"; continue; }

    # collect to NAS + OAL
    bash /Cold-Archive/OpenAudioLab/scripts/collect_lora.sh "$RUN" "$f" && log "collected $f" || log "collect FAILED $f"
done
log "batch complete"
