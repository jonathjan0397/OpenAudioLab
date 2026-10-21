#!/bin/bash
set -euo pipefail
IMAGE=stratastack/oal-worker:house-v1-070-int8
DB='postgresql+psycopg2://oal:993903361d4157b90803f309e6a0f6d2@10.203.0.1:55432/oal'
REDIS='redis://:3acc81a98ee300acba919d424164e0e5@10.203.0.1:6379/0'
SECRET=4022736855959b810ab98d772ab1af94af9f0b222495595c996479145915f5cc

docker rm -f oal-worker-hub oal-worker-gpu1 2>/dev/null || true

docker run -d --name oal-worker-hub --gpus all --network host --restart unless-stopped \
  -e CUDA_VISIBLE_DEVICES=0 \
  -e ACESTEP_API_HOST=0.0.0.0 -e ACESTEP_API_PORT=8001 -e ACESTEP_DEVICE=cuda:0 -e ACESTEP_INIT_LLM=true \
  -e ACESTEP_OFFLOAD_TO_CPU=1 \
  -e ACESTEP_LM_BACKEND=pt \
  -e ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-1.7B \
  -e ACESTEP_QUANTIZATION=int8_weight_only \
  -e ACESTEP_CONFIG_PATH=acestep-v15-house-turbo -e OAL_ACESTEP_MODEL=acestep-v15-house-turbo \
  -e OAL_ACESTEP_BASE_URL=http://127.0.0.1:8001 -e OAL_APP_DIR=/srv/openaudiolab/code \
  -e OAL_BACKEND_URL=http://10.203.0.1:50555 -e OAL_DATABASE_URL="$DB" \
  -e OAL_DEMUCS_DEVICE=cuda -e OAL_DEMUCS_PYTHON=/usr/local/bin/python \
  -e OAL_ENGINE_IDLE_STOP_SECONDS=600 -e OAL_REDIS_URL="$REDIS" -e OAL_SECRET_KEY="$SECRET" \
  -e OAL_STORAGE_BACKEND=local -e OAL_STORAGE_DIR=/data/oal \
  -e OAL_TRAIN_WORKDIR=/opt/acestep/training-data -e OAL_TRAIN_MIN_FREE_MB=0 \
  -e OAL_TRAIN_HTTP_TIMEOUT_SECONDS=7200 -e OAL_ENGINE_AUTOSTART=1 \
  -e OAL_PREMIUM_PROFILES_ENABLED=sft-quality-v1,xl-sft-quality-v1,xl-turbo-fast-v1 \
  -e OAL_XL_CHECKPOINT_ID=acestep-v15-xl-sft \
  -e OAL_XL_TURBO_CHECKPOINT_ID=acestep-v15-xl-turbo \
  -e OAL_WORKER_ID=oal-baseline-gpu0 \
  -e OAL_LLM_AUTOSTART=0 \
  -e OAL_LLM_CTX=4096 \
  -e OAL_LLM_GPU_LAYERS=99 \
  -e OAL_WORKER_ROLE=engine_worker,audio_worker -e OAL_WORKER_TIER=baseline \
  -v /mnt/oal-storage:/data/oal -v oal-acestep-cache:/root/.cache \
  -v /Cold-Archive/oal-train-gpu0:/opt/acestep/training-data \
  -v /Cold-Archive/oal-models/acestep-v15-sft:/opt/acestep/checkpoints/acestep-v15-sft \
  -v /Cold-Archive/oal-models/acestep-v15-xl-sft:/opt/acestep/checkpoints/acestep-v15-xl-sft \
  -v /Cold-Archive/oal-models/acestep-v15-xl-turbo:/opt/acestep/checkpoints/acestep-v15-xl-turbo \
  "$IMAGE"

docker run -d --name oal-worker-gpu1 --gpus all --restart unless-stopped \
  -e CUDA_VISIBLE_DEVICES=1 \
  -e ACESTEP_API_HOST=0.0.0.0 -e ACESTEP_API_PORT=8001 -e ACESTEP_DEVICE=cuda:0 -e ACESTEP_INIT_LLM=true \
  -e OAL_ACESTEP_BASE_URL=http://127.0.0.1:8001 -e OAL_APP_DIR=/srv/openaudiolab/code \
  -e OAL_BACKEND_URL=http://10.203.0.1:50555 -e OAL_DATABASE_URL="$DB" \
  -e OAL_DEMUCS_DEVICE=cuda -e OAL_DEMUCS_PYTHON=/usr/local/bin/python \
  -e OAL_ENGINE_IDLE_STOP_SECONDS=600 -e OAL_REDIS_URL="$REDIS" -e OAL_SECRET_KEY="$SECRET" \
  -e OAL_STORAGE_BACKEND=local -e OAL_STORAGE_DIR=/data/oal \
  -e OAL_TRAIN_WORKDIR=/opt/acestep/training-data-gpu1 -e OAL_TRAIN_MIN_FREE_MB=0 \
  -e OAL_TRAIN_HTTP_TIMEOUT_SECONDS=7200 -e OAL_ENGINE_AUTOSTART=0 \
  -e OAL_WORKER_ID=oal-training-gpu1 \
  -e OAL_WORKER_ROLE=training_worker -e OAL_WORKER_TIER=baseline \
  -v /mnt/oal-storage:/data/oal -v oal-acestep-cache-gpu1:/root/.cache \
  -v /Cold-Archive/oal-train-gpu1:/opt/acestep/training-data-gpu1 \
   "$IMAGE"

# Drafting lyrics LLM (Qwen3-4B): its OWN CPU-only container on this host, kept OFF
# the GPU worker so XL/SFT premium has VRAM. Reuses the worker image's baked
# llama-server + model (no download). The backend's llm_base_url -> :8082/v1.
docker rm -f oal-llm 2>/dev/null || true
docker run -d --name oal-llm --restart unless-stopped -p 8082:8082 \
  --entrypoint /usr/local/bin/llama-server "$IMAGE" \
  --model /opt/llm/qwen3-4b-q4_k_m.gguf --host 0.0.0.0 --port 8082 \
  --ctx-size 4096 --n-gpu-layers 0 --alias qwen3-4b --flash-attn off --reasoning-budget 512

sleep 5
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E "oal-worker|oal-llm"
