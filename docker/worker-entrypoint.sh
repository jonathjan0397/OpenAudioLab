#!/bin/sh
# Combined worker entrypoint: optionally bring up the WireGuard tunnel, fetch
# our app code from the backend over the tunnel, start the co-located ACE-Step
# server, then run the worker role(s). The heavy runtime lives in the image;
# only our code is transferred.
set -e

# Optional self-contained WireGuard bring-up (needs NET_ADMIN + a mounted
# /etc/wireguard/wg0.conf). Skipped when the host already provides the tunnel.
if [ "${OAL_WG_UP:-0}" = "1" ] && [ -f /etc/wireguard/wg0.conf ]; then
    echo "[worker] bringing up WireGuard (wg0)"
    wg-quick up wg0 || { echo "[worker] wg-quick up failed"; exit 1; }
fi

BACKEND="${OAL_BACKEND_URL:-http://10.0.0.1:50555}"
APP_DIR="${OAL_APP_DIR:-/srv/openaudiolab/code}"
ROLES=$(printf '%s' "${OAL_WORKER_ROLE:-engine_worker}" | tr ',' ' ')

mkdir -p "$APP_DIR"
echo "[worker] fetching code bundle from $BACKEND"
i=0
until curl -fsSL "$BACKEND/internal/v1/worker/bundle" -o /tmp/bundle.tgz; do
    i=$((i + 1))
    [ "$i" -ge 60 ] && { echo "[worker] bundle fetch failed"; exit 1; }
    sleep 3
done
tar -xzf /tmp/bundle.tgz -C "$APP_DIR"
echo "[worker] code revision: $(cat "$APP_DIR/REVISION" 2>/dev/null || echo unknown)"

echo "[worker] starting ACE-Step server"
( cd /opt/acestep && exec uv run acestep-api ) &
i=0
until curl -fsS "http://127.0.0.1:8001/health" >/dev/null 2>&1; do
    i=$((i + 1))
    [ "$i" -ge 120 ] && { echo "[worker] ACE-Step server not ready"; exit 1; }
    sleep 5
done
echo "[worker] ACE-Step server ready"

export PYTHONPATH="$APP_DIR"
cd "$APP_DIR"
set -- $ROLES
for role in "$@"; do
    echo "[worker] starting $role"
    python -m "app.$role" &
done
wait
