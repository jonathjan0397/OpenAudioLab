#!/usr/bin/env bash
# Collect a finished house LoRA run into the local NAS archive and register it
# in Open Audio Lab (postgres + object-storage share).
#
#   collect_lora.sh <run_id> <family>
#
# Pulls adapter + epoch checkpoints + logs from the hub, copies the local
# tensors/dataset/selection, writes a manifest.json, copies the adapter into the
# OAL storage share (loras/<family>/), and inserts a Lora row into OAL postgres.
set -euo pipefail

RUN_ID="${1:?usage: collect_lora.sh <run_id> <family>}"
FAMILY="${2:?usage: collect_lora.sh <run_id> <family>}"

HUB="administrator@192.151.156.124"
HUBPW="3671A113a05786!"
HUB_SRC="/srv/oal-storage/house-lora/${RUN_ID}"
SSH="sshpass -p ${HUBPW} ssh -o StrictHostKeyChecking=no"
RS="sshpass -p ${HUBPW} rsync -a -e 'ssh -o StrictHostKeyChecking=no'"

NAS="/Cold-Archive/OpenAudioLab/TrainingData/${FAMILY}"
SEL="/Cold-Archive/OpenAudioLab/curation/selection_perfamily"
OAL_ROOT="/srv/oal-storage/oal"         # hub object-storage root (NFS, owned by uid 10001)
DBURL="postgresql://oal:993903361d4157b90803f309e6a0f6d2@127.0.0.1:55432/oal"

echo "[collect] run=${RUN_ID} family=${FAMILY} -> ${NAS}"
mkdir -p "${NAS}"

# 1) adapter + checkpoints + logs from the hub
eval ${RS} "${HUB}:${HUB_SRC}/adapter/"      "${NAS}/adapter/"
if ${SSH} "${HUB}" "test -d ${HUB_SRC}/checkpoints"; then
    eval ${RS} "${HUB}:${HUB_SRC}/checkpoints/" "${NAS}/checkpoints/"
fi
${SSH} "${HUB}" "cat ${HUB_SRC}/status.json" > "${NAS}/status.json" 2>/dev/null || true
${SSH} "${HUB}" "cat ${HUB_SRC}/api.log"     > "${NAS}/api.log"     2>/dev/null || true

# 2) local tensors / dataset / selection
cp -f "${SEL}/tensors-${FAMILY}.tar.zst" "${NAS}/tensors.tar.zst" 2>/dev/null || echo "[collect] warn: no tensors-${FAMILY}.tar.zst"
cp -f "${SEL}/${FAMILY}_dataset.json"    "${NAS}/dataset.json"    2>/dev/null || echo "[collect] warn: no ${FAMILY}_dataset.json"
cp -f "${SEL}/${FAMILY}.jsonl"           "${NAS}/selection.jsonl" 2>/dev/null || echo "[collect] warn: no ${FAMILY}.jsonl"

# 3) manifest.json
TRACKS=$(wc -l < "${NAS}/selection.jsonl" 2>/dev/null || echo 0)
python3 - "$NAS" "$RUN_ID" "$FAMILY" "$TRACKS" <<'PY'
import json, sys, re, datetime, os
nas, run_id, family, tracks = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4] or 0)
losses = {}
log = os.path.join(nas, "api.log")
if os.path.exists(log):
    for m in re.finditer(r"epoch_(\d+)_loss_([0-9.]+)", open(log, errors="ignore").read()):
        losses[int(m.group(1))] = float(m.group(2))
final = None
sj = os.path.join(nas, "status.json")
if os.path.exists(sj):
    try:
        final = (json.load(open(sj)).get("data") or {}).get("current_loss")
    except Exception:
        pass
manifest = {
    "family": family, "run_id": run_id, "base_model": "ace-step-1.5",
    "tracks": tracks, "epochs": 15, "rank": 64, "alpha": 128, "lr": 1e-4,
    "seed": 42, "batch_size": 1, "gradient_accumulation": 4, "save_every": 5,
    "epoch_losses": dict(sorted(losses.items())), "final_loss": final,
    "source": "vast-4090 (house-agent)", "provenance": "trained",
    "collected_utc": datetime.datetime.utcnow().isoformat() + "Z",
}
json.dump(manifest, open(os.path.join(nas, "manifest.json"), "w"), indent=2)
print("[collect] manifest:", json.dumps(manifest["epoch_losses"]))
PY

# 4) copy adapter into OAL storage share (loras/<family>/) on the HUB
#    (the NFS share is owned by uid 10001; the dev host can't write it directly).
${SSH} "${HUB}" "echo ${HUBPW} | sudo -S mkdir -p ${OAL_ROOT}/loras/${FAMILY} \
    && echo ${HUBPW} | sudo -S cp ${HUB_SRC}/adapter/adapter_config.json ${HUB_SRC}/adapter/adapter_model.safetensors ${OAL_ROOT}/loras/${FAMILY}/ \
    && echo ${HUBPW} | sudo -S chown -R 10001:10001 ${OAL_ROOT}/loras/${FAMILY}" \
    || echo "[collect] warn: OAL share copy failed"

# 5) insert Lora row into OAL postgres (idempotent by name)
${SSH} "${HUB}" "DBURL='${DBURL}' FAMILY='${FAMILY}' /home/administrator/OpenAudioLab/.venv/bin/python - <<'PY'
import os, json, uuid, psycopg2, psycopg2.extras
from datetime import datetime, timezone
psycopg2.extras.register_default_json(loads=json.loads)
url = os.environ['DBURL']; fam = os.environ['FAMILY']
c = psycopg2.connect(url); cur = c.cursor()
cur.execute('SELECT 1 FROM loras WHERE name=%s', (fam,))
if cur.fetchone():
    print('[collect] lora row exists for', fam)
else:
    cur.execute(
        'INSERT INTO loras (id,name,kind,tags_json,storage_prefix,files_json,base_model_id,'
        'base_revision,default_scale,state,provenance,adapter_id,auto_apply,priority,created_at) '
        'VALUES (%s,%s,%s,%s::json,%s,%s::json,%s,%s,%s,%s,%s,NULL,%s,%s,%s)',
        (str(uuid.uuid4()), fam, 'genre', json.dumps([fam]), f'loras/{fam}',
         json.dumps(['adapter_config.json', 'adapter_model.safetensors']),
         'ace-step-1.5', '', 1.0, 'active', 'trained', True, 0, datetime.now(timezone.utc)))
    c.commit(); print('[collect] inserted lora row for', fam)
c.close()
PY"

echo "[collect] done: $(du -sh "${NAS}" 2>/dev/null | cut -f1) at ${NAS}"
