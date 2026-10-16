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

# Optional Tailscale userspace bring-up for Vast nodes (no NET_ADMIN needed).
# The hub's services are then reachable at its 100.x address.
if [ "${OAL_TS_UP:-0}" = "1" ]; then
    TS_SOCK=/tmp/tailscale/tailscaled.sock
    mkdir -p /tmp/tailscale
    echo "[worker] starting tailscaled (userspace networking)"
    tailscaled --tun=userspace-networking --statedir=/tmp/tailscale --socket="$TS_SOCK" \
        >/tmp/tailscale/tailscaled.log 2>&1 &
    i=0
    until tailscale --socket="$TS_SOCK" version >/dev/null 2>&1; do
        i=$((i + 1))
        [ "$i" -ge 30 ] && { echo "[worker] tailscaled not ready"; exit 1; }
        sleep 1
    done
    TS_ARGS="--auth-key=${OAL_TS_AUTHKEY} --hostname=${OAL_TS_HOSTNAME:-oal-worker}"
    [ -n "${OAL_TS_TAGS:-}" ] && TS_ARGS="$TS_ARGS --advertise-tags=$OAL_TS_TAGS"
    echo "[worker] joining tailnet"
    # shellcheck disable=SC2086
    tailscale --socket="$TS_SOCK" up $TS_ARGS || { echo "[worker] tailscale up failed"; exit 1; }
    tailscale --socket="$TS_SOCK" ip -4
fi

# Optional hub NFS mount for the local filesystem storage backend (Vast nodes
# mount inside the container; trusted hosts bind-mount the dir instead).
if [ -n "${OAL_NFS_SOURCE:-}" ]; then
    NFS_TARGET="${OAL_NFS_TARGET:-/data/oal}"
    mkdir -p "$NFS_TARGET"
    echo "[worker] mounting $OAL_NFS_SOURCE -> $NFS_TARGET"
    i=0
    until mount -t nfs4 -o timeo=50,retrans=3 "$OAL_NFS_SOURCE" "$NFS_TARGET"; do
        i=$((i + 1))
        [ "$i" -ge 20 ] && { echo "[worker] NFS mount failed"; exit 1; }
        sleep 3
    done
fi

# rsync push-back for nodes that cannot mount NFS (Vast lacks CAP_SYS_ADMIN):
# the worker writes to local disk and a sidecar loop mirrors it to the hub.
if [ -n "${OAL_PUSH_TARGET:-}" ]; then
    if [ -n "${OAL_PUSH_PRIVKEY_B64:-}" ]; then
        mkdir -p /root/.ssh
        printf '%s' "${OAL_PUSH_PRIVKEY_B64}" | base64 -d > /root/.ssh/oal_deploy
        chmod 600 /root/.ssh/oal_deploy
    fi
    SSH_RSYNC="ssh -i /root/.ssh/oal_deploy -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
    mkdir -p "${OAL_STORAGE_DIR:-/data/oal}"
    echo "[worker] push-back loop -> $OAL_PUSH_TARGET"
    (
        while true; do
            rsync -aq -e "$SSH_RSYNC" "${OAL_STORAGE_DIR:-/data/oal}/" "$OAL_PUSH_TARGET" 2>/dev/null || true
            sleep 2
        done
    ) &
    PUSH_PID=$!
    trap 'kill $PUSH_PID 2>/dev/null; rsync -aq -e "$SSH_RSYNC" "${OAL_STORAGE_DIR:-/data/oal}/" "$OAL_PUSH_TARGET" 2>/dev/null || true' TERM
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

if [ "${OAL_ENGINE_AUTOSTART:-1}" = "0" ]; then
    echo "[worker] starting ACE-Step server (external mode)"
    ( cd /opt/acestep && exec uv run acestep-api ) &
    i=0
    until curl -fsS "http://127.0.0.1:8001/health" >/dev/null 2>&1; do
        i=$((i + 1))
        [ "$i" -ge 120 ] && { echo "[worker] ACE-Step server not ready"; exit 1; }
        sleep 5
    done
    echo "[worker] ACE-Step server ready"
else
    echo "[worker] ACE-Step server managed by engine_worker (lazy start, idle-stop)"
fi

export PYTHONPATH="$APP_DIR"
cd "$APP_DIR"
set -- $ROLES
for role in "$@"; do
    echo "[worker] starting $role"
    python -m "app.$role" &
done
wait
