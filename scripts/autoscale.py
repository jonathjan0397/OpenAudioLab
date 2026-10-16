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

Vast workers reach the hub over its public IP (Vast containers lack NET_ADMIN,
so in-container WireGuard is unavailable) and use args launch mode. Run this on
the hub (home server): it needs the vastai CLI + hub reachability (redis is
local there) and does not need a GPU.

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

import redis

HUB = os.environ.get("OAL_HUB_IP", "192.151.156.124")
QUEUE_KEY = os.environ.get("OAL_QUEUE_KEY", "oal:queue:ace-step-1.5")
BURST_KEY = QUEUE_KEY + ":burst"
REDIS_URL = os.environ.get("OAL_REDIS_URL", f"redis://{HUB}:6379/0")
IMAGE = os.environ.get("OAL_WORKER_IMAGE", "stratastack/oal-worker:ca1e85f-torch2.10-cu128-wg")
DISK = os.environ.get("OAL_VAST_DISK", "40")
SCALE_UP = int(os.environ.get("OAL_SCALE_UP_DEPTH", "2"))
JOBS_PER_NODE = int(os.environ.get("OAL_SCALE_JOBS_PER_NODE", "8"))
MAX_NODES = int(os.environ.get("OAL_SCALE_MAX_NODES", "3"))
BASELINE = int(os.environ.get("OAL_SCALE_BASELINE_WORKERS", "1"))
SCALE_DOWN_SECONDS = float(os.environ.get("OAL_SCALE_DOWN_SECONDS", "1800"))
TO_ONE_SECONDS = float(os.environ.get("OAL_SCALE_TO_ONE_SECONDS", "300"))
MIN_UPTIME = float(os.environ.get("OAL_VAST_MIN_UPTIME", "180"))
POLL = float(os.environ.get("OAL_SCALE_POLL_SECONDS", "15"))
STATE = os.environ.get("OAL_AUTOSCALE_STATE", "/tmp/oal_autoscale_state.json")
VASTAI = os.environ.get("VASTAI", "vastai")
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


def worker_env():
    pw = os.environ["OAL_POSTGRES_PASSWORD"]
    secret = os.environ["OAL_SECRET_KEY"]
    s3a = os.environ.get("OAL_S3_ACCESS_KEY", "oal")
    s3s = os.environ["OAL_S3_SECRET_KEY"]
    bucket = os.environ.get("OAL_S3_BUCKET", "oal")
    region = os.environ.get("OAL_S3_REGION", "us-east-1")
    return " ".join([
        f"-e OAL_BACKEND_URL=http://{HUB}:50555",
        f"-e OAL_REDIS_URL=redis://{HUB}:6379/0",
        f"-e OAL_DATABASE_URL=postgresql+psycopg2://oal:{pw}@{HUB}:55432/oal",
        "-e OAL_STORAGE_BACKEND=s3",
        f"-e OAL_S3_ENDPOINT_URL=http://{HUB}:9000",
        f"-e OAL_S3_BUCKET={bucket}",
        f"-e OAL_S3_REGION={region}",
        f"-e OAL_S3_ACCESS_KEY={s3a}",
        f"-e OAL_S3_SECRET_KEY={s3s}",
        f"-e OAL_SECRET_KEY={secret}",
        "-e OAL_WORKER_ROLE=engine_worker",
        "-e OAL_ACESTEP_BASE_URL=http://127.0.0.1:8001",
        # Burst tier: Vast nodes drain only the overflow queue, so the always-on
        # baseline worker keeps first claim on the main queue.
        "-e OAL_WORKER_TIER=burst",
        # Vast burst nodes stay hot (keep the model loaded for their short life);
        # the autoscaler tears them down, so no idle-stop is needed.
        "-e OAL_ENGINE_IDLE_STOP_SECONDS=0",
    ])


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


def create_instance(dry_run=False):
    offer = pick_offer()
    if not offer:
        log("no eligible North-American offer; will retry")
        return None
    if dry_run:
        log(f"[dry-run] would create instance on offer {offer}")
        return -1
    _, out, _ = sh([VASTAI, "create", "instance", str(offer), "--image", IMAGE,
                    "--disk", DISK, "--env", worker_env(), "--args", "run"])
    ok = "'success': True" in out
    m = re.search(r"'new_contract':\s*(\d+)", out)
    log(f"create offer={offer} ok={ok} out={out.strip()[:160]}")
    # Track the instance whenever Vast returned a contract, even if the CLI
    # reported success:False -- the node booted and is billing, so leaving it
    # untracked would leak it. Only a create with no contract is a true failure.
    return int(m.group(1)) if m else None


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
        new = create_instance(dry_run)
        if new:
            nodes.append({"contract": new, "created_at": now})
            st["nodes"] = nodes
            log(f"depth={depth} want={want} -> +1 node {new} (now {len(nodes)})")
    elif len(nodes) > want:
        removable = [n for n in nodes if now - n["created_at"] >= MIN_UPTIME]
        if not removable:
            log(f"depth={depth} want={want} nodes={len(nodes)} all < min_uptime; hold")
        else:
            victim = max(removable, key=lambda n: n["created_at"])  # newest first
            destroy_instance(victim["contract"], dry_run)
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
