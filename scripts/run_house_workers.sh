#!/bin/bash
set -euo pipefail
IMAGE=stratastack/oal-worker:5eaa583-torch2.10-cu128-ts7
DB='postgresql+psycopg2://oal:993903361d4157b90803f309e6a0f6d2@10.203.0.1:55432/oal'
REDIS='redis://:3acc81a98ee300acba919d424164e0e5@10.203.0.1:6379/0'
SECRET=4022736855959b810ab98d772ab1af94af9f0b222495595c996479145915f5cc

docker rm -f oal-worker-hub oal-worker-gpu1 2>/dev/null || true

docker run -d --name oal-worker-hub --gpus all --network host --restart unless-stopped \
  -e ACESTEP_API_HOST=0.0.0.0 -e ACESTEP_API_PORT=8001 -e ACESTEP_DEVICE=cuda:0 -e ACESTEP_INIT_LLM=false \
  -e OAL_ACESTEP_BASE_URL=http://127.0.0.1:8001 -e OAL_APP_DIR=/srv/openaudiolab/code \
  -e OAL_BACKEND_URL=http://10.203.0.1:50555 -e OAL_DATABASE_URL="$DB" \
  -e OAL_DEMUCS_DEVICE=cuda -e OAL_DEMUCS_PYTHON=/usr/local/bin/python \
  -e OAL_ENGINE_IDLE_STOP_SECONDS=600 -e OAL_REDIS_URL="$REDIS" -e OAL_SECRET_KEY="$SECRET" \
  -e OAL_STORAGE_BACKEND=local -e OAL_STORAGE_DIR=/data/oal \
  -e OAL_TRAIN_WORKDIR=/opt/acestep/training-data -e OAL_TRAIN_MIN_FREE_MB=0 \
  -e OAL_TRAIN_HTTP_TIMEOUT_SECONDS=7200 -e OAL_ENGINE_AUTOSTART=0 \
  -e OAL_WORKER_ROLE=training_worker,audio_worker -e OAL_WORKER_TIER=baseline \
  -v /mnt/oal-storage:/data/oal -v oal-acestep-cache:/root/.cache \
  "$IMAGE"

docker run -d --name oal-worker-gpu1 --gpus all --restart unless-stopped \
  -e CUDA_VISIBLE_DEVICES=1 \
  -e ACESTEP_API_HOST=0.0.0.0 -e ACESTEP_API_PORT=8001 -e ACESTEP_DEVICE=cuda:0 -e ACESTEP_INIT_LLM=false \
  -e OAL_ACESTEP_BASE_URL=http://127.0.0.1:8001 -e OAL_APP_DIR=/srv/openaudiolab/code \
  -e OAL_BACKEND_URL=http://10.203.0.1:50555 -e OAL_DATABASE_URL="$DB" \
  -e OAL_DEMUCS_DEVICE=cuda -e OAL_DEMUCS_PYTHON=/usr/local/bin/python \
  -e OAL_ENGINE_IDLE_STOP_SECONDS=600 -e OAL_REDIS_URL="$REDIS" -e OAL_SECRET_KEY="$SECRET" \
  -e OAL_STORAGE_BACKEND=local -e OAL_STORAGE_DIR=/data/oal \
  -e OAL_TRAIN_WORKDIR=/opt/acestep/training-data-gpu1 -e OAL_TRAIN_MIN_FREE_MB=0 \
  -e OAL_TRAIN_HTTP_TIMEOUT_SECONDS=7200 -e OAL_ENGINE_AUTOSTART=0 \
  -e OAL_WORKER_ROLE=training_worker -e OAL_WORKER_TIER=baseline \
  -v /mnt/oal-storage:/data/oal -v oal-acestep-cache-gpu1:/root/.cache \
  "$IMAGE"

sleep 5
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E "oal-worker"
