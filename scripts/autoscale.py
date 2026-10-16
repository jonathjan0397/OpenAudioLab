#!/usr/bin/env python3
"""Queue-depth autoscaler for OpenAudioLab engine workers.

Policy (multi-node, tiered scale-down): the local GPU worker (dev host, GPU 0)
is the always-on baseline (OAL_SCALE_BASELINE_WORKERS, default 1). Desired Vast
burst nodes = 0 while the queue is below OAL_SCALE_UP_DEPTH, else
max(0, min(ceil(depth / OAL_SCALE_JOBS_PER_NODE), OAL_SCALE_MAX_NODES) -
baseline) -- OAL_SCALE_MAX_NODES caps TOTAL workers (baseline + Vast); we add at
most one Vast node per tick. Scale-down is driven by
how long demand has been low (depth < OAL_SCALE_UP_DEPTH): hold the fleet for
OAL_SCALE_TO_ONE_SECONDS, then drop to one hot node, then tear it down after
OAL_SCALE_DOWN_SECONDS of low demand; any spike back to >= OAL_SCALE_UP_DEPTH
resets the timer. A node younger than OAL_VAST_MIN_UPTIME is never removed.

Vast workers reach the hub over Tailscale when OAL_TS_AUTHKEY + OAL_HUB_TS_IP
are set (tailscaled runs in userspace mode inside the container -- Vast hosts
deny NET_ADMIN, so kernel WireGuard fails there); otherwise they join the hub's
WireGuard pool (per-node keypair + pooled 10.203.0.x address, hub-side
`wg set wg2 peer`, needs `sudo -n wg`). Nodes use args launch mode.
Run this on the hub (home server): it needs the vastai CLI + hub reachability
(redis is local there) and does not need a GPU.

Config comes from the environment; source the hub secrets first, e.g.:
    set -a; . .env.backend; set +a
    OAL_HUB_IP=192.151.156.124 OAL_REDIS_URL=redis://127.0.0.1:6379/0 \
      VASTAI=.venv/bin/vastai .venv/bin/python scripts/autoscale.py
"""
import argparse
import json
import math
import os
import re
import subprocess
import time
import uuid

import redis

HUB = os.environ.get("OAL_HUB_IP", "192.151.156.124")
HUB_TUNNEL = os.environ.get("OAL_HUB_TUNNEL_IP", "10.203.0.1")
QUEUE_KEY = os.environ.get("OAL_QUEUE_KEY", "oal:queue:ace-step-1.5")
BURST_KEY = QUEUE_KEY + ":burst"
REDIS_URL = os.environ.get("OAL_REDIS_URL", f"redis://{HUB}:6379/0")
IMAGE = os.environ.get("OAL_WORKER_IMAGE", "stratastack/oal-worker:ca1e85f-torch2.10-cu128-wg")
DISK = os.environ.get("OAL_VAST_DISK", "40")
SCALE_UP = int(os.environ.get("OAL_SCALE_UP_DEPTH", "2"))
JOBS_PER_NODE = int(os.environ.get("OAL_SCALE_JOBS_PER_NODE", "20"))
MAX_NODES = int(os.environ.get("OAL_SCALE_MAX_NODES", "3"))
BASELINE = int(os.environ.get("OAL_SCALE_BASELINE_WORKERS", "1"))
SCALE_DOWN_SECONDS = float(os.environ.get("OAL_SCALE_DOWN_SECONDS", "1800"))
TO_ONE_SECONDS = float(os.environ.get("OAL_SCALE_TO_ONE_SECONDS", "300"))
MIN_UPTIME = float(os.environ.get("OAL_VAST_MIN_UPTIME", "180"))
POLL = float(os.environ.get("OAL_SCALE_POLL_SECONDS", "15"))
STATE = os.environ.get("OAL_AUTOSCALE_STATE", "/tmp/oal_autoscale_state.json")
VASTAI = os.environ.get("VASTAI", "vastai")
# WireGuard peer pool for Vast burst nodes (hub iface wg2, 10.203.0.0/24).
# The autoscaler runs on the hub; wg set needs root, so run it under sudo or
# grant passwordless `sudo -n wg`.
WG_HUB_PUBKEY = os.environ.get("OAL_WG_HUB_PUBKEY", "")
WG_IFACE = os.environ.get("OAL_WG_IFACE", "wg2")
WG_POOL_START = int(os.environ.get("OAL_WG_POOL_START", "10"))
WG_POOL_SIZE = int(os.environ.get("OAL_WG_POOL_SIZE", "16"))
WG_SUDO = os.environ.get("OAL_WG_SUDO", "sudo -n").split()
# Tailscale transport (preferred for Vast: userspace mode needs no NET_ADMIN).
# When both are set, Vast nodes join the tailnet instead of the wg2 pool.
TS_AUTHKEY = os.environ.get("OAL_TS_AUTHKEY", "")
TS_TAGS = os.environ.get("OAL_TS_TAGS", "")
HUB_TS = os.environ.get("OAL_HUB_TS_IP", "")
PUSH_PRIVKEY_B64 = os.environ.get("OAL_PUSH_PRIVKEY_B64", "")
REDIS_PASSWORD = os.environ.get("OAL_REDIS_PASSWORD", "")
# Vast transport: "public" (hub public IP + ssh push-back; Vast lacks the caps
# for kernel WireGuard/NFS and userspace Tailscale cannot route raw app TCP),
# or "ts"/"wg" for capable hosts.
VAST_TRANSPORT = os.environ.get("OAL_VAST_TRANSPORT", "public")
MIN_RELIABILITY = float(os.environ.get("OAL_VAST_MIN_RELIABILITY", "0.95"))
# Exclude old architectures (e.g. Volta V100 = 7.0) that the cu128 ACE-Step build
# is not validated on; keeps Turing/Ampere/Ada/Blackwell.
MIN_COMPUTE_CAP = float(os.environ.get("OAL_VAST_MIN_COMPUTE_CAP", "7.5"))
# Approx worker image size (GB), used only to estimate cold-start pull time when
# ranking offers by cost-per-download-Mbps (cheapest AND fastest to pull).
IMAGE_GB = float(os.environ.get("OAL_WORKER_IMAGE_GB", "13"))


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def sh(args, stdin=None):
    p = subprocess.run(args, capture_output=True, text=True, input=stdin)
    return p.returncode, p.stdout, p.stderr


def worker_env(transport="wg", slot=None):
    pw = os.environ["OAL_POSTGRES_PASSWORD"]
    secret = os.environ["OAL_SECRET_KEY"]
    base = HUB_TS if transport == "ts" else (HUB_TUNNEL if transport == "wg" else HUB)
    env = [
        f"-e OAL_BACKEND_URL=http://{base}:50555",
        f"-e OAL_REDIS_URL=redis://:{REDIS_PASSWORD}@{base}:6379/0" if REDIS_PASSWORD
        else f"-e OAL_REDIS_URL=redis://{base}:6379/0",
        f"-e OAL_DATABASE_URL=postgresql+psycopg2://oal:{pw}@{base}:55432/oal",
        "-e OAL_STORAGE_BACKEND=local",
        "-e OAL_STORAGE_DIR=/data/oal",
        f"-e OAL_SECRET_KEY={secret}",
        "-e OAL_WORKER_ROLE=engine_worker",
        "-e OAL_ACESTEP_BASE_URL=http://127.0.0.1:8001",
        # Burst tier: Vast nodes drain only the overflow queue, so the always-on
        # baseline worker keeps first claim on the main queue.
        "-e OAL_WORKER_TIER=burst",
        # Vast burst nodes stay hot (keep the model loaded for their short life);
        # the autoscaler tears them down, so no idle-stop is needed.
        "-e OAL_ENGINE_IDLE_STOP_SECONDS=0",
    ]
    if transport in ("ts", "public"):
        # Vast containers cannot mount NFS (no CAP_SYS_ADMIN): write to local
        # disk and rsync-push to the hub over ssh instead.
        if transport == "ts":
            env += [
                "-e OAL_TS_UP=1",
                f"-e OAL_TS_AUTHKEY={TS_AUTHKEY}",
                f"-e OAL_TS_HOSTNAME={slot['hostname'] if slot else 'oal-vast'}",
            ]
            if TS_TAGS:
                env.append(f"-e OAL_TS_TAGS={TS_TAGS}")
        env += [
            f"-e OAL_PUSH_TARGET=administrator@{base}:/srv/oal-storage/oal/",
            f"-e OAL_PUSH_PRIVKEY_B64={PUSH_PRIVKEY_B64}",
        ]
    else:
        env.append(f"-e OAL_NFS_SOURCE={base}:/srv/oal-storage/oal")
        env.append("-e OAL_NFS_TARGET=/data/oal")
        if slot:
            env += [
                "-e OAL_WG_UP=1",
                f"-e OAL_WG_PRIVKEY={slot['privkey']}",
                f"-e OAL_WG_ADDRESS={slot['ip']}/24",
                f"-e OAL_WG_PUBKEY={WG_HUB_PUBKEY}",
                f"-e OAL_WG_ENDPOINT={HUB}:51822",
            ]
    return " ".join(env)


def gen_ts_slot():
    return {"hostname": f"oal-vast-{uuid.uuid4().hex[:6]}"}


def gen_wg_slot(nodes):
    """Generate a keypair and pick a free 10.203.0.x address from the pool."""
    rc, priv, _ = sh(["wg", "genkey"])
    if rc or not priv.strip():
        return None
    rc, pub, _ = sh(["wg", "pubkey"], stdin=priv.strip())
    if rc or not pub.strip():
        return None
    used = {n.get("wg_ip") for n in nodes}
    for i in range(WG_POOL_START, WG_POOL_START + WG_POOL_SIZE):
        ip = f"10.203.0.{i}"
        if ip not in used:
            return {"privkey": priv.strip(), "pubkey": pub.strip(), "ip": ip}
    return None


def wg_add_peer(pub, ip):
    sh(WG_SUDO + ["wg", "set", WG_IFACE, "peer", pub, "allowed-ips", f"{ip}/32"])


def wg_remove_peer(pub):
    sh(WG_SUDO + ["wg", "set", WG_IFACE, "peer", pub, "remove"])


def pick_offer():
    _, out, _ = sh([VASTAI, "search", "offers",
                    "gpu_ram>=16 num_gpus=1 rentable=true cuda_max_good>=12.8 verification=verified",
                    "--raw", "-o", "dph_total", "--limit", "200"])
    try:
        offers = json.loads(out)
    except Exception:
        return None
    # Rank by an image-pull-cost proxy: hourly price per Mbps of download. This
    # favours offers that are BOTH cheap and fast to pull (cold start is the
    # dominant burst cost), rather than the cheapest-but-slowest node.
    best = None
    for o in offers:
        geo = str(o.get("geolocation", ""))
        cc = o.get("compute_cap") or 0
        rel = o.get("reliability2") or 0
        dph = o.get("dph_total") or 0
        down = o.get("inet_down") or 0
        if not (geo.endswith(", US") or geo.endswith(", CA")):
            continue
        if rel < MIN_RELIABILITY or cc < MIN_COMPUTE_CAP or dph <= 0 or down <= 0:
            continue
        score = dph / down
        if best is None or score < best[0]:
            best = (score, o)
    if not best:
        return None
    o = best[1]
    pull_min = IMAGE_GB * 8000 / (o.get("inet_down") or 1) / 60
    log(f"picked offer {o.get('id')} {o.get('gpu_name')} {o.get('geolocation')} "
        f"dph=${o.get('dph_total'):.3f}/hr inet_down={o.get('inet_down')}Mbps "
        f"~pull={pull_min:.1f}min score={best[0]:.5f}")
    return o.get("id")


def create_instance(slot=None, dry_run=False, transport="wg"):
    offer = pick_offer()
    if not offer:
        log("no eligible North-American offer; will retry")
        return None
    if dry_run:
        log(f"[dry-run] would create instance on offer {offer}")
        return -1
    env = ("--privileged " if transport == "wg" else "") + worker_env(transport, slot)
    _, out, _ = sh([VASTAI, "create", "instance", str(offer), "--image", IMAGE,
                    "--disk", DISK, "--env", env, "--args", "run"])
    ok = "'success': True" in out
    m = re.search(r"'new_contract':\s*(\d+)", out)
    log(f"create offer={offer} ok={ok} out={out.strip()[:160]}")
    # Track the instance whenever Vast returned a contract, even if the CLI
    # reported success:False -- the node booted and is billing, so leaving it
    # untracked would leak it. Only a create with no contract is a true failure.
    cid = int(m.group(1)) if m else None
    if cid and slot and transport == "wg":
        wg_add_peer(slot["pubkey"], slot["ip"])
    return cid


def destroy_instance(cid, dry_run=False):
    if dry_run:
        log(f"[dry-run] would destroy instance {cid}")
        return
    _, out, _ = sh([VASTAI, "destroy", "instance", str(cid)], stdin="y\n")
    log(f"destroy {cid}: {out.strip()[-80:]}")


def load_state():
    try:
        with open(STATE) as f:
            st = json.load(f)
    except Exception:
        st = {}
    # Backward-compat: old single-contract state -> node list.
    if "nodes" not in st:
        cid = st.get("contract")
        st["nodes"] = (
            [{"contract": cid, "created_at": st.get("created_at") or time.time()}]
            if cid else []
        )
        st.setdefault("low_since", None)
    return st


def save_state(st):
    with open(STATE, "w") as f:
        json.dump(st, f)


def desired_nodes(depth, low_since, now, current):
    """Target number of Vast burst nodes for the current queue state."""
    if depth >= SCALE_UP:
        total = min(math.ceil(depth / JOBS_PER_NODE), MAX_NODES)
        return max(0, total - BASELINE)
    # Demand has subsided (depth < SCALE_UP): tier down by how long it has been low.
    if low_since is None:
        return current  # just dropped below threshold; hold during grace
    age = now - low_since
    if age < TO_ONE_SECONDS:
        return current  # grace: keep the fleet briefly in case it is a lull
    if age < SCALE_DOWN_SECONDS:
        return 1        # keep one hot node for follow-up work
    return 0            # sustained drain: tear everything down


def tick(r, st, dry_run=False):
    depth = r.llen(QUEUE_KEY) + r.llen(BURST_KEY)
    now = time.time()
    nodes = st.get("nodes", [])
    if depth >= SCALE_UP:
        st["low_since"] = None
    elif st.get("low_since") is None:
        st["low_since"] = now
    want = desired_nodes(depth, st.get("low_since"), now, len(nodes))

    if len(nodes) < want:
        transport = VAST_TRANSPORT
        if transport == "ts":
            slot = gen_ts_slot()
        elif transport == "wg":
            slot = gen_wg_slot(nodes)
            if slot is None:
                log("WireGuard pool exhausted; creating without tunnel")
        else:
            slot = None
        new = create_instance(slot, dry_run, transport)
        if new:
            node = {"contract": new, "created_at": now, "transport": transport}
            if transport == "ts" and slot:
                node["ts_hostname"] = slot["hostname"]
            elif transport == "wg" and slot:
                node.update({"wg_ip": slot["ip"], "wg_pubkey": slot["pubkey"],
                             "wg_privkey": slot["privkey"]})
            nodes.append(node)
            st["nodes"] = nodes
            log(f"depth={depth} want={want} -> +1 node {new} via {transport} (now {len(nodes)})")
    elif len(nodes) > want:
        removable = [n for n in nodes if now - n["created_at"] >= MIN_UPTIME]
        burst_depth = r.llen(BURST_KEY)
        if removable and burst_depth > 0:
            removable = []
            hold_reason = f"burst={burst_depth} draining"
        else:
            hold_reason = "all < min_uptime"
        if not removable:
            log(f"depth={depth} want={want} nodes={len(nodes)} {hold_reason}; hold")
        else:
            victim = max(removable, key=lambda n: n["created_at"])  # newest first
            destroy_instance(victim["contract"], dry_run)
            if victim.get("wg_pubkey") and not dry_run:
                wg_remove_peer(victim["wg_pubkey"])
            nodes.remove(victim)
            st["nodes"] = nodes
            log(f"depth={depth} want={want} -> -1 node {victim['contract']} (now {len(nodes)})")
    return depth


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="evaluate one pass and exit")
    ap.add_argument("--dry-run", action="store_true", help="log actions without calling Vast")
    args = ap.parse_args()

    r = redis.Redis.from_url(REDIS_URL, socket_timeout=5)
    st = load_state()
    # Re-add tracked WireGuard peers in case wg2 was restarted (dynamic peers
    # are lost on interface restart).
    for n in st.get("nodes", []):
        if n.get("wg_pubkey") and n.get("wg_ip"):
            wg_add_peer(n["wg_pubkey"], n["wg_ip"])
    log(f"start hub={HUB} queue={QUEUE_KEY} up>={SCALE_UP} jobs/node={JOBS_PER_NODE} "
        f"max={MAX_NODES} baseline={BASELINE} to_one>{int(TO_ONE_SECONDS)}s "
        f"down>{int(SCALE_DOWN_SECONDS)}s min_uptime={int(MIN_UPTIME)}s state={st}")
    while True:
        try:
            depth = tick(r, st, args.dry_run)
            save_state(st)
        except Exception as e:
            log(f"tick error: {e}")
        if args.once:
            break
        time.sleep(POLL)


if __name__ == "__main__":
    main()
