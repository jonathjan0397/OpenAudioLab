#!/usr/bin/env python3
"""Queue-depth autoscaler for OpenAudioLab engine workers.

Policy: the local GPU worker (dev host, GPU 0) is the always-on baseline. When
the engine queue backs up to OAL_SCALE_UP_DEPTH jobs we spin up ONE Vast.ai
burst worker to help drain it, and tear it down once the queue is empty for
OAL_SCALE_DOWN_SECONDS (after a minimum uptime so it is not killed mid-boot).

Vast workers reach the hub over its public IP (Vast containers lack NET_ADMIN,
so in-container WireGuard is unavailable) and use args launch mode. Run this on
the dev host (has GPU 0, the vastai CLI, and hub reachability).

Config comes from the environment; source the hub secrets first, e.g.:
    set -a; . .env.backend; set +a
    OAL_HUB_IP=192.151.156.124 VASTAI=.venv/bin/vastai \
      .venv/bin/python scripts/autoscale.py
"""
import argparse
import json
import os
import re
import subprocess
import time

import redis

HUB = os.environ.get("OAL_HUB_IP", "192.151.156.124")
QUEUE_KEY = os.environ.get("OAL_QUEUE_KEY", "oal:queue:ace-step-1.5")
REDIS_URL = os.environ.get("OAL_REDIS_URL", f"redis://{HUB}:6379/0")
IMAGE = os.environ.get("OAL_WORKER_IMAGE", "stratastack/oal-worker:ca1e85f-torch2.10-cu128-wg")
DISK = os.environ.get("OAL_VAST_DISK", "40")
SCALE_UP = int(os.environ.get("OAL_SCALE_UP_DEPTH", "2"))
SCALE_DOWN_SECONDS = float(os.environ.get("OAL_SCALE_DOWN_SECONDS", "120"))
MIN_UPTIME = float(os.environ.get("OAL_VAST_MIN_UPTIME", "180"))
POLL = float(os.environ.get("OAL_SCALE_POLL_SECONDS", "15"))
STATE = os.environ.get("OAL_AUTOSCALE_STATE", "/tmp/oal_autoscale_state.json")
VASTAI = os.environ.get("VASTAI", "vastai")
MIN_RELIABILITY = float(os.environ.get("OAL_VAST_MIN_RELIABILITY", "0.95"))
# Exclude old architectures (e.g. Volta V100 = 7.0) that the cu128 ACE-Step build
# is not validated on; keeps Turing/Ampere/Ada/Blackwell.
MIN_COMPUTE_CAP = float(os.environ.get("OAL_VAST_MIN_COMPUTE_CAP", "7.5"))


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
    ])


def pick_offer():
    _, out, _ = sh([VASTAI, "search", "offers",
                    "gpu_ram>=16 num_gpus=1 rentable=true cuda_max_good>=12.8 verification=verified",
                    "--raw", "-o", "dph_total"])
    try:
        offers = json.loads(out)
    except Exception:
        return None
    for o in offers:
        geo = str(o.get("geolocation", ""))
        cc = o.get("compute_cap") or 0
        if (geo.endswith(", US") or geo.endswith(", CA")) \
                and (o.get("reliability2") or 0) >= MIN_RELIABILITY \
                and cc >= MIN_COMPUTE_CAP:
            return o.get("id")
    return None


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
    return int(m.group(1)) if (ok and m) else None


def destroy_instance(cid, dry_run=False):
    if dry_run:
        log(f"[dry-run] would destroy instance {cid}")
        return
    _, out, _ = sh([VASTAI, "destroy", "instance", str(cid)], stdin="y\n")
    log(f"destroy {cid}: {out.strip()[-80:]}")


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {"contract": None, "created_at": None, "idle_since": None}


def save_state(st):
    with open(STATE, "w") as f:
        json.dump(st, f)


def tick(r, st, dry_run=False):
    depth = r.llen(QUEUE_KEY)
    cid = st.get("contract")
    now = time.time()
    if cid is None:
        if depth >= SCALE_UP:
            log(f"depth={depth} >= {SCALE_UP} -> spin up Vast burst worker")
            new = create_instance(dry_run)
            if new:
                st.update(contract=new, created_at=now, idle_since=None)
    else:
        if depth == 0:
            if now - (st.get("created_at") or 0) < MIN_UPTIME:
                log(f"depth=0 but instance {cid} still warming "
                    f"({int(now - st['created_at'])}s < {int(MIN_UPTIME)}s)")
            elif st.get("idle_since") is None:
                st["idle_since"] = now
                log(f"depth=0 -> idle timer started for {cid}")
            elif now - st["idle_since"] >= SCALE_DOWN_SECONDS:
                log(f"drained for {int(now - st['idle_since'])}s -> tear down {cid}")
                destroy_instance(cid, dry_run)
                st.update(contract=None, created_at=None, idle_since=None)
        elif st.get("idle_since") is not None:
            st["idle_since"] = None
            log(f"depth={depth} -> cancel idle timer")
    return depth


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="evaluate one pass and exit")
    ap.add_argument("--dry-run", action="store_true", help="log actions without calling Vast")
    args = ap.parse_args()

    r = redis.Redis.from_url(REDIS_URL, socket_timeout=5)
    st = load_state()
    log(f"start hub={HUB} queue={QUEUE_KEY} up>={SCALE_UP} down>{int(SCALE_DOWN_SECONDS)}s "
        f"min_uptime={int(MIN_UPTIME)}s state={st}")
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
