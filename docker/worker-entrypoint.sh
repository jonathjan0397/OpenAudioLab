#!/bin/sh
# Combined worker entrypoint: optionally bring up the WireGuard tunnel, fetch
# our app code from the backend over the tunnel, start the co-located ACE-Step
# server, then run the worker role(s). The heavy runtime lives in the image;
# only our code is transferred.
set -e

# Optional self-contained WireGuard bring-up (needs NET_ADMIN). When enabled and
# no config is mounted, write /etc/wireguard/wg0.conf from env so a Vast-style
# container needs no bind-mount.
if [ "${OAL_WG_UP:-0}" = "1" ]; then
    mkdir -p /etc/wireguard
    if [ ! -f /etc/wireguard/wg0.conf ] && [ -n "${OAL_WG_PRIVKEY:-}" ]; then
        cat > /etc/wireguard/wg0.conf <<WG
[Interface]
PrivateKey = ${OAL_WG_PRIVKEY}
Address = ${OAL_WG_ADDRESS}
ListenPort = ${OAL_WG_PORT:-51820}

[Peer]
PublicKey = ${OAL_WG_PUBKEY}
Endpoint = ${OAL_WG_ENDPOINT}
AllowedIPs = ${OAL_WG_ALLOWED:-10.203.0.0/24}
PersistentKeepalive = 25
WG
    fi
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
