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
IMAGE = os.environ.get("OAL_WORKER_IMAGE", "stratastack/oal-worker:house-v1-070-int8")
DISK = os.environ.get("OAL_VAST_DISK", "90")
SCALE_UP = int(os.environ.get("OAL_SCALE_UP_DEPTH", "2"))
# R15: workload-aware demand. A queued job's estimated GPU seconds is
# (base + per-minute * duration) * family factor. Factors are PROVISIONAL
# starting values until the XL benchmark records baselines (Phase 4 gate).
WORK_BASE_SECONDS = float(os.environ.get("OAL_SCALE_WORK_BASE_SECONDS", "45"))
WORK_SECONDS_PER_MINUTE = float(os.environ.get("OAL_SCALE_WORK_SECONDS_PER_MINUTE", "30"))
DEFAULT_JOB_SECONDS = float(os.environ.get("OAL_SCALE_DEFAULT_JOB_SECONDS", "120"))
FAMILY_FACTORS = {
    k: float(v) for k, v in (
        pair.split("=", 1) for pair in os.environ.get(
            "OAL_SCALE_FAMILY_FACTORS", "turbo=1.0,sft=2.0,xl=2.5,merge=2.0"
        ).split(",") if "=" in pair
    )
}
JOBS_PER_NODE = int(os.environ.get("OAL_SCALE_JOBS_PER_NODE", "20"))
MAX_NODES = int(os.environ.get("OAL_SCALE_MAX_NODES", "3"))
BASELINE = int(os.environ.get("OAL_SCALE_BASELINE_WORKERS", "1"))
SCALE_DOWN_SECONDS = float(os.environ.get("OAL_SCALE_DOWN_SECONDS", "1800"))
TO_ONE_SECONDS = float(os.environ.get("OAL_SCALE_TO_ONE_SECONDS", "300"))
MIN_UPTIME = float(os.environ.get("OAL_VAST_MIN_UPTIME", "180"))
POLL = float(os.environ.get("OAL_SCALE_POLL_SECONDS", "15"))
STATE = os.environ.get("OAL_AUTOSCALE_STATE", "/var/tmp/oal_autoscale_state.json")
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
# Instance reuse (M16): scale-down STOPS nodes instead of destroying them and
# scale-up restarts a recently stopped node before creating a fresh one.
REUSE = os.environ.get("OAL_VAST_REUSE", "1") != "0"
KEEP_STOPPED = int(os.environ.get("OAL_VAST_KEEP_STOPPED", "2"))
RECONCILE_SECONDS = float(os.environ.get("OAL_VAST_RECONCILE_SECONDS", "120"))
# Training tier: pending UAIS voice jobs get a dedicated Vast training node
# after OAL_TRAIN_VAST_AFTER_SECONDS (giving the gated local worker first
# claim); idle nodes are stopped after OAL_TRAIN_DOWN_SECONDS. Two pools:
# 2B adapters on cheap >=24 GB offers, XL (4B) adapters on larger offers with
# a separate dph ceiling (all classes remote; first runs double as the XL
# VRAM/time benchmark).
TRAIN_QUEUE = os.environ.get("OAL_TRAIN_QUEUE_KEY", "oal:queue:training")
TRAIN_QUEUE_XL = os.environ.get("OAL_TRAIN_XL_QUEUE_KEY", "oal:queue:training-xl")
TRAIN_WAIT_LOCAL = float(os.environ.get("OAL_TRAIN_VAST_AFTER_SECONDS", "120"))
TRAIN_DOWN_SECONDS = float(os.environ.get("OAL_TRAIN_DOWN_SECONDS", "240"))
TRAIN_LOADING_STALL_SECONDS = float(os.environ.get("OAL_TRAIN_LOADING_STALL_SECONDS", "1200"))
TRAIN_CREATE_GUARD_SECONDS = float(os.environ.get("OAL_TRAIN_CREATE_GUARD_SECONDS", "600"))
TRAIN_MAX_NODES = int(os.environ.get("OAL_TRAIN_MAX_NODES", "1"))
TRAIN_XL_MAX_NODES = int(os.environ.get("OAL_TRAIN_XL_MAX_NODES", "1"))
TRAIN_XL_MIN_VRAM = os.environ.get("OAL_TRAIN_XL_MIN_VRAM", "32")
TRAIN_XL_MAX_DPH = float(os.environ.get("OAL_TRAIN_XL_MAX_DPH", "0.60"))
# Optional training-specific image (defaults to the engine worker image; the
# UAIS decision is slim image + runtime checkpoint download).
TRAIN_IMAGE = os.environ.get("OAL_TRAIN_WORKER_IMAGE", "")
MAX_DPH = float(os.environ.get("OAL_SCALE_MAX_DPH", "0.40"))  # 0 = uncapped (R9: never default to unlimited spend)
PRUNE_SECONDS = float(os.environ.get("OAL_PRUNE_SECONDS", "3600"))
RETENTION_DAYS = int(os.environ.get("OAL_RETENTION_DAYS", "30"))
# Baseline fallback: when the always-on dev worker is unhealthy, create one
# low-cost North-American node that consumes the main queue and serves the LLM.
BASELINE_WORKER_ID = os.environ.get("OAL_BASELINE_WORKER_ID", "")
BASELINE_HEALTH_SECONDS = float(os.environ.get("OAL_BASELINE_HEALTH_SECONDS", "60"))
BASELINE_UNAVAILABLE_GRACE_SECONDS = float(os.environ.get("OAL_BASELINE_UNAVAILABLE_GRACE_SECONDS", "300"))
BASELINE_RESTORE_GRACE_SECONDS = float(os.environ.get("OAL_BASELINE_RESTORE_GRACE_SECONDS", "300"))
BASELINE_FALLBACK_MAX_DPH = float(os.environ.get("OAL_BASELINE_FALLBACK_MAX_DPH", "0.15"))
BASELINE_FALLBACK_MIN_VRAM = os.environ.get("OAL_BASELINE_FALLBACK_MIN_VRAM", "24")
BASELINE_FALLBACK_MIN_COMPUTE_CAP = float(os.environ.get("OAL_BASELINE_FALLBACK_MIN_COMPUTE_CAP", "7.0"))
BASELINE_FALLBACK_ROLE = os.environ.get("OAL_BASELINE_FALLBACK_ROLE", "engine_worker,audio_worker")
BASELINE_FALLBACK_CREATE_GUARD_SECONDS = float(os.environ.get("OAL_BASELINE_FALLBACK_CREATE_GUARD_SECONDS", "120"))
PRIMARY_LLM_BASE_URL = os.environ.get("OAL_PRIMARY_LLM_BASE_URL", "")
LLM_PORT = os.environ.get("OAL_LLM_PORT", "8082")
# When set, generation (engine/audio) nodes load this baked checkpoint instead
# of the image default. Training nodes keep the base DiT so LoRAs train against
# the unmerged model.
ACESTEP_MODEL = os.environ.get("OAL_ACESTEP_MODEL", "")

# Offers whose instances repeatedly die during boot ("stuck loading") go here
# for a few hours so pick_offer stops re-buying the same broken host.
OFFER_COOLDOWN_SECONDS = float(os.environ.get("OAL_OFFER_COOLDOWN_SECONDS", "10800"))
OFFER_COOLDOWN = {}       # offer_id -> unix ts until which the offer is banned
_OFFER_OF_CONTRACT = {}   # contract id -> offer id of the create that made it
_OFFER_DPH = {}           # offer id -> $/hr at pick time (cost accounting)
for _seed in os.environ.get("OAL_OFFER_COOLDOWN", "").split(","):
    _seed = _seed.strip()
    if "-" in _seed and _seed.replace("-", "").isdigit():
        _lo, _hi = _seed.split("-", 1)
        for _oid in range(int(_lo), int(_hi) + 1):
            OFFER_COOLDOWN[str(_oid)] = time.time() + OFFER_COOLDOWN_SECONDS
    elif _seed:
        OFFER_COOLDOWN[_seed] = time.time() + OFFER_COOLDOWN_SECONDS


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


# --- Vast instance registry (best-effort DB mirror for the Admin UI) ---------
_DB = None
_DB_FAILED = False


def _engine():
    global _DB, _DB_FAILED
    if _DB_FAILED:
        return None
    if _DB is None:
        url = os.environ.get("OAL_DATABASE_URL", "")
        if not url:
            _DB_FAILED = True
            return None
        try:
            import sqlalchemy

            _DB = sqlalchemy.create_engine(url, pool_pre_ping=True, pool_recycle=300)
        except Exception as e:
            log(f"registry db unavailable: {e}")
            _DB_FAILED = True
            return None
    return _DB


def registry_upsert(cid, role, state, gpu=None, dph=None):
    d = _engine()
    if d is None:
        return
    try:
        from sqlalchemy import text

        with d.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO vast_instances (id, vast_instance_id, role, gpu_model, dph, state, created_at, last_used_at) "
                    "VALUES (gen_random_uuid()::text, :cid, :role, :gpu, :dph, :state, now(), now()) "
                    "ON CONFLICT (vast_instance_id) DO UPDATE SET state = EXCLUDED.state, role = EXCLUDED.role, "
                    "gpu_model = COALESCE(EXCLUDED.gpu_model, vast_instances.gpu_model), "
                    "dph = COALESCE(EXCLUDED.dph, vast_instances.dph), last_used_at = now()"
                ),
                {"cid": str(cid), "role": role, "gpu": gpu, "dph": dph, "state": state},
            )
    except Exception as e:
        log(f"registry upsert failed: {e}")


def registry_set(cid, state):
    d = _engine()
    if d is None:
        return
    try:
        from sqlalchemy import text

        with d.begin() as conn:
            conn.execute(
                text(
                    "UPDATE vast_instances SET state = :state, "
                    "stopped_at = CASE WHEN :state = 'stopped' THEN now() ELSE stopped_at END, "
                    "last_used_at = now() WHERE vast_instance_id = :cid"
                ),
                {"state": state, "cid": str(cid)},
            )
    except Exception as e:
        log(f"registry set failed: {e}")


def registry_remove(cid):
    d = _engine()
    if d is None:
        return
    try:
        from sqlalchemy import text

        with d.begin() as conn:
            conn.execute(text("DELETE FROM vast_instances WHERE vast_instance_id = :cid"), {"cid": str(cid)})
    except Exception as e:
        log(f"registry remove failed: {e}")


def baseline_available():
    """True when the tracked baseline worker is healthy or actively working.

    If no baseline id is configured, or the DB is unavailable, assume the
    historical behavior: the local baseline exists. This avoids false fallbacks
    during DB/CLI hiccups.
    """
    if not BASELINE_WORKER_ID:
        return True
    d = _engine()
    if d is None:
        return True
    try:
        from sqlalchemy import text

        sql = text(
            """
            select exists (
                select 1
                from workers w
                where w.id = :wid
                  and w.drain = false
                  and (w.unhealthy_until is null or w.unhealthy_until < now())
                  and (
                    w.last_heartbeat > now() - make_interval(secs => :health)
                    or exists (
                        select 1
                        from job_attempts ja
                        where ja.worker_id = :wid
                          and ja.status = 'running'
                          and ja.heartbeat_at > now() - make_interval(secs => :health)
                    )
                  )
            ) as ok
            """
        )
        with d.connect() as conn:
            return bool(conn.execute(sql, {"wid": BASELINE_WORKER_ID, "health": BASELINE_HEALTH_SECONDS}).scalar())
    except Exception as e:
        log(f"baseline health check failed: {e}")
        return True


def set_llm_endpoint(url):
    d = _engine()
    if d is None:
        return
    try:
        from sqlalchemy import text

        with d.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO site_settings (key, value, updated_at) VALUES ('llm_base_url', :url, now()) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
                ),
                {"url": url or ""},
            )
    except Exception as e:
        log(f"llm endpoint update failed: {e}")


def instance_public_ip(cid):
    _, out, _ = sh([VASTAI, "show", "instances", "--raw"])
    try:
        rows = json.loads(out)
    except Exception:
        return None
    for row in rows:
        if str(row.get("id")) == str(cid):
            return row.get("public_ipaddr") or row.get("public_ip") or row.get("ip")
    return None


def instance_public_endpoint(cid, container_port=None):
    _, out, _ = sh([VASTAI, "show", "instances", "--raw"])
    try:
        rows = json.loads(out)
    except Exception:
        return None, None
    container_port = str(container_port or LLM_PORT)
    for row in rows:
        if str(row.get("id")) != str(cid):
            continue
        ip = row.get("public_ipaddr") or row.get("public_ip") or row.get("ip")
        port = None
        for key, bindings in (row.get("ports") or {}).items():
            if key.split("/", 1)[0] == container_port and bindings:
                port = bindings[0].get("HostPort")
                break
        return ip, port or container_port
    return None, None


def sh(args, stdin=None):
    p = subprocess.run(args, capture_output=True, text=True, input=stdin)
    return p.returncode, p.stdout, p.stderr


def worker_env(transport="wg", slot=None, role="engine_worker", tier=None, llm=False, train_queue=None):
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
        f"-e OAL_WORKER_ROLE={role}",
        "-e OAL_ACESTEP_BASE_URL=http://127.0.0.1:8001",
    ]
    if llm:
        env += [
            "-e OAL_LLM_AUTOSTART=1",
            f"-e OAL_LLM_PORT={LLM_PORT}",
            "-e OAL_LLM_HOST=0.0.0.0",
            "-e OAL_LLM_MODEL=/opt/llm/qwen3-4b-q4_k_m.gguf",
            "-e OAL_LLM_MODEL_NAME=qwen3-4b",
        ]
    if role == "training_worker":
        # Training node: engine runs in external mode (entrypoint starts and
        # health-checks it) so the training worker can rely on it without an
        # engine_worker process also claiming generation jobs.
        env += [
            "-e OAL_ENGINE_AUTOSTART=0",
            # Absolute workdir: the default ./training-data resolves against
            # the container CWD and the engine rejects it as unsafe.
            "-e OAL_TRAIN_WORKDIR=/opt/acestep/training-data",
            # The node's own engine holds most VRAM; without this the training
            # worker defers forever waiting for free memory that never comes.
            "-e OAL_TRAIN_MIN_FREE_MB=0",
            # Large datasets: scan/preprocess are blocking HTTP calls; the 30 m
            # default kills 1000+-track jobs mid-preprocess.
            "-e OAL_TRAIN_HTTP_TIMEOUT_SECONDS=7200",
        ]
        if train_queue:
            # Pin the node to one training queue (2B pool: "training";
            # XL pool: "training-xl") so pools never steal each other's jobs.
            env += [
                f"-e OAL_TRAIN_QUEUE_MODEL_ID={train_queue}",
                f"-e OAL_TRAIN_XL_QUEUE_MODEL_ID={train_queue}",
            ]
    else:
        # Burst tier: Vast nodes drain only the overflow queue, so the always-on
        # baseline worker keeps first claim on the main queue. Baseline fallback
        # nodes override this and consume the main queue while the dev worker is
        # unavailable.
        env += [
            f"-e OAL_WORKER_TIER={tier or 'burst'}",
            # Vast burst nodes stay hot (keep the model loaded for their short
            # life); the autoscaler tears them down, so no idle-stop is needed.
            "-e OAL_ENGINE_IDLE_STOP_SECONDS=0",
        ]
        if ACESTEP_MODEL:
            env += [
                f"-e ACESTEP_CONFIG_PATH={ACESTEP_MODEL}",
                f"-e OAL_ACESTEP_MODEL={ACESTEP_MODEL}",
            ]
        if os.environ.get("OAL_VAST_PREMIUM", "1") != "0":
            # XL/SFT premium on 24GB+ Vast nodes: the 5Hz-LM planner (1.7B, pt
            # backend) for coherent vocal/long audio; int8 applies ONLY to XL via the
            # baked patch (turbo/SFT stay bf16 so their 2B LoRAs load); CPU offload;
            # checkpoints pull from HuggingFace on first premium job. pick_offer gates
            # nodes to >=24GB; profiles self-gate on vram_required_mb. Disable with
            # OAL_VAST_PREMIUM=0 (turbo-only Vast).
            env += [
                "-e ACESTEP_INIT_LLM=true",
                "-e ACESTEP_LM_BACKEND=pt",
                "-e ACESTEP_LM_MODEL_PATH=acestep-5Hz-lm-1.7B",
                "-e ACESTEP_QUANTIZATION=int8_weight_only",
                "-e ACESTEP_OFFLOAD_TO_CPU=1",
                "-e OAL_PREMIUM_PROFILES_ENABLED=sft-quality-v1,xl-sft-quality-v1,xl-turbo-fast-v1",
                "-e OAL_XL_CHECKPOINT_ID=acestep-v15-xl-sft",
                "-e OAL_XL_TURBO_CHECKPOINT_ID=acestep-v15-xl-turbo",
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


def pick_offer(max_dph=None, min_compute=None, min_vram=None):
    max_dph = MAX_DPH if max_dph is None else max_dph
    min_compute = MIN_COMPUTE_CAP if min_compute is None else min_compute
    min_vram = "24" if min_vram is None else str(min_vram)
    _, out, _ = sh([VASTAI, "search", "offers",
                    f"gpu_ram>={min_vram} num_gpus=1 rentable=true cuda_max_good>=12.8 verification=verified",
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
        if OFFER_COOLDOWN.get(str(o.get("id")), 0) > time.time():
            continue
        geo = str(o.get("geolocation", ""))
        cc = o.get("compute_cap") or 0
        rel = o.get("reliability2") or 0
        dph = o.get("dph_total") or 0
        down = o.get("inet_down") or 0
        if not (geo.endswith(", US") or geo.endswith(", CA")):
            continue
        if rel < MIN_RELIABILITY or cc < min_compute or dph <= 0 or down <= 0:
            continue
        if max_dph and dph > max_dph:
            continue
        # The instance's --disk request must fit on the host disk (with headroom
        # for the image layers and the host's own reservation). Offers whose
        # disk_space is smaller than the request get silently capped -> ENOSPC
        # mid-download (~40min wasted per attempt).
        if (o.get("disk_space") or 0) < int(DISK) + 30:
            continue
        score = dph / down
        if best is None or score < best[0]:
            best = (score, o)
    if not best:
        return None
    o = best[1]
    _OFFER_DPH[str(o.get("id"))] = float(o.get("dph_total") or 0.0)
    pull_min = IMAGE_GB * 8000 / (o.get("inet_down") or 1) / 60
    log(f"picked offer {o.get('id')} {o.get('gpu_name')} {o.get('geolocation')} "
        f"dph=${o.get('dph_total'):.3f}/hr inet_down={o.get('inet_down')}Mbps "
        f"~pull={pull_min:.1f}min score={best[0]:.5f}")
    return o.get("id")


def create_instance(
    slot=None,
    dry_run=False,
    transport="wg",
    role="engine_worker",
    tier=None,
    llm=False,
    max_dph=None,
    min_compute=None,
    min_vram=None,
    image=None,
    train_queue=None,
):
    offer = pick_offer(max_dph=max_dph, min_compute=min_compute, min_vram=min_vram)
    if not offer:
        log("no eligible North-American offer; will retry")
        return None
    if dry_run:
        log(f"[dry-run] would create instance on offer {offer}")
        return -1
    env = ("--privileged " if transport == "wg" else "") + worker_env(
        transport, slot, role, tier=tier, llm=llm, train_queue=train_queue)
    if llm:
        env += f" -p {LLM_PORT}:{LLM_PORT}/tcp"
    cmd = [VASTAI, "create", "instance", str(offer), "--image", image or IMAGE, "--disk", DISK, "--env", env]
    cmd += ["--args", "run"]
    _, out, _ = sh(cmd)
    ok = "'success': True" in out
    m = re.search(r"'new_contract':\s*(\d+)", out)
    log(f"create offer={offer} ok={ok} out={out.strip()[:160]}")
    # Track the instance whenever Vast returned a contract, even if the CLI
    # reported success:False -- the node booted and is billing, so leaving it
    # untracked would leak it. Only a create with no contract is a true failure.
    cid = int(m.group(1)) if m else None
    if cid:
        _OFFER_OF_CONTRACT[str(cid)] = str(offer)
    if cid and slot and transport == "wg":
        wg_add_peer(slot["pubkey"], slot["ip"])
    if cid:
        registry_upsert(cid, "training" if role == "training_worker" else "engine", "running",
                        dph=_OFFER_DPH.get(str(offer)))
    return cid


def stop_instance(cid, dry_run=False):
    if dry_run:
        log(f"[dry-run] would stop instance {cid}")
        return True
    _, out, _ = sh([VASTAI, "stop", "instance", str(cid)])
    log(f"stop {cid}: {out.strip()[-80:]}")
    return True


def start_instance(cid, dry_run=False):
    if dry_run:
        log(f"[dry-run] would start instance {cid}")
        return True
    _, out, _ = sh([VASTAI, "start", "instance", str(cid)])
    ok = "'success': True" in out
    log(f"start {cid}: ok={ok} {out.strip()[-80:]}")
    return ok


def destroy_instance(cid, dry_run=False):
    if dry_run:
        log(f"[dry-run] would destroy instance {cid}")
        return
    _, out, _ = sh([VASTAI, "destroy", "instance", str(cid)], stdin="y\n")
    log(f"destroy {cid}: {out.strip()[-80:]}")


def live_statuses():
    """Map of vast instance id -> actual_status, or None if the CLI failed."""
    _, out, _ = sh([VASTAI, "show", "instances", "--raw"])
    try:
        rows = json.loads(out)
    except Exception:
        return None
    return {str(r.get("id")): str(r.get("actual_status", "")) for r in rows}


def prune():
    """30-day rotation: job_events, error_logs, and purging soft-deleted users."""
    d = _engine()
    if d is None:
        return
    try:
        from sqlalchemy import text

        with d.begin() as conn:
            conn.execute(text(
                "DELETE FROM job_events WHERE created_at < now() - make_interval(days => :days)"
            ), {"days": RETENTION_DAYS})
            conn.execute(text(
                "DELETE FROM error_logs WHERE created_at < now() - make_interval(days => :days)"
            ), {"days": RETENTION_DAYS})
            conn.execute(text(
                "DELETE FROM users WHERE deleted_at IS NOT NULL "
                "AND deleted_at < now() - make_interval(days => :days)"
            ), {"days": RETENTION_DAYS})
    except Exception as e:
        log(f"prune failed: {e}")


def reconcile(st):
    """Drop state entries Vast no longer knows about (evicted stopped nodes)."""
    statuses = live_statuses()
    if statuses is None:
        return
    now = time.time()
    alive = {"running", "starting", "creating", "restarting", "warming", "processing", "rebooting", "loading"}
    for key in ("nodes", "train_nodes"):
        kept = []
        for n in st.get(key, []):
            cid = str(n["contract"])
            status = statuses.get(cid)
            if status == "loading":
                n["loading_since"] = n.get("loading_since") or n.get("created_at") or now
                if now - n["loading_since"] > TRAIN_LOADING_STALL_SECONDS:
                    log(f"reconcile: {key} node {cid} stuck loading >{int(TRAIN_LOADING_STALL_SECONDS)}s -> destroy")
                    destroy_instance(cid, False)
                    registry_remove(cid)
                    off = _OFFER_OF_CONTRACT.get(cid)
                    if off:
                        OFFER_COOLDOWN[off] = now + OFFER_COOLDOWN_SECONDS
                        log(f"reconcile: offer {off} (contract {cid}) failed to boot; cooling down {int(OFFER_COOLDOWN_SECONDS/60)}min")
                else:
                    kept.append(n)
                continue
            n.pop("loading_since", None)
            if cid in statuses and status in alive:
                n.pop("missing_since", None)
                kept.append(n)
            elif cid not in statuses:
                # Transient CLI gaps happen; only evict after a grace window.
                n["missing_since"] = n.get("missing_since") or now
                if now - n["missing_since"] > 300:
                    log(f"reconcile: {key} node {cid} missing from Vast >300s")
                    registry_remove(cid)
                else:
                    kept.append(n)
            else:
                log(f"reconcile: {key} node {cid} gone from Vast ({status})")
                registry_remove(cid)
        st[key] = kept
    for key in ("stopped", "train_stopped"):
        kept = []
        for n in st.get(key, []):
            cid = str(n["contract"])
            if cid in statuses:
                kept.append(n)
            else:
                log(f"reconcile: {key} node {cid} evicted from Vast")
                registry_remove(cid)
        st[key] = kept
    fb = st.get("fallback_node")
    if fb:
        cid = str(fb["contract"])
        status = statuses.get(cid)
        if cid in statuses and status in alive:
            fb.pop("missing_since", None)
        elif cid not in statuses:
            fb["missing_since"] = fb.get("missing_since") or now
            if now - fb["missing_since"] > 300:
                log(f"reconcile: fallback node {cid} missing from Vast >300s")
                registry_remove(cid)
                set_llm_endpoint(PRIMARY_LLM_BASE_URL)
                st["fallback_node"] = None
        else:
            log(f"reconcile: fallback node {cid} gone from Vast ({status})")
            registry_remove(cid)
            set_llm_endpoint(PRIMARY_LLM_BASE_URL)
            st["fallback_node"] = None


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


def desired_nodes(depth, low_since, now, current, effective_baseline=None):
    """Target number of Vast burst nodes for the current queue state."""
    effective_baseline = BASELINE if effective_baseline is None else effective_baseline
    if depth >= SCALE_UP:
        total = min(math.ceil(depth / JOBS_PER_NODE), MAX_NODES)
        return max(0, total - effective_baseline)
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
    # R15: scale on estimated work, not raw count — a few XL jobs weigh more than
    # many turbo jobs. depth_eff is the workload-equivalent job count.
    depth_eff = max(depth, math.ceil(queued_work_seconds(r) / DEFAULT_JOB_SECONDS))
    now = time.time()
    nodes = st.get("nodes", [])
    if depth_eff >= SCALE_UP:
        st["low_since"] = None
    elif st.get("low_since") is None:
        st["low_since"] = now

    baseline_ok = baseline_available()
    fallback = st.get("fallback_node")
    if baseline_ok:
        st["baseline_unavailable_since"] = None
        if fallback:
            st["baseline_restored_since"] = st.get("baseline_restored_since") or now
            if now - st["baseline_restored_since"] >= BASELINE_RESTORE_GRACE_SECONDS:
                cid = fallback["contract"]
                destroy_instance(cid, dry_run)
                if fallback.get("wg_pubkey") and not dry_run:
                    wg_remove_peer(fallback["wg_pubkey"])
                registry_remove(cid)
                set_llm_endpoint(PRIMARY_LLM_BASE_URL)
                st["fallback_node"] = None
                st["baseline_restored_since"] = None
                log(f"baseline restored -> destroyed fallback node {cid}")
        else:
            st["baseline_restored_since"] = None
    else:
        st["baseline_restored_since"] = None
        st["baseline_unavailable_since"] = st.get("baseline_unavailable_since") or now
        if not fallback:
            unavailable_age = now - st["baseline_unavailable_since"]
            last_attempt = st.get("fallback_last_attempt") or 0
            if unavailable_age >= BASELINE_UNAVAILABLE_GRACE_SECONDS and now - last_attempt >= BASELINE_FALLBACK_CREATE_GUARD_SECONDS:
                st["fallback_last_attempt"] = now
                transport = VAST_TRANSPORT
                slot = gen_ts_slot() if transport == "ts" else None
                cid = create_instance(
                    slot,
                    dry_run,
                    transport,
                    role=BASELINE_FALLBACK_ROLE,
                    tier="baseline",
                    llm=True,
                    max_dph=BASELINE_FALLBACK_MAX_DPH,
                    min_compute=BASELINE_FALLBACK_MIN_COMPUTE_CAP,
                    min_vram=BASELINE_FALLBACK_MIN_VRAM,
                )
                if cid:
                    node = {"contract": cid, "created_at": now, "transport": transport, "llm_endpoint_set": False}
                    if transport == "ts" and slot:
                        node["ts_hostname"] = slot["hostname"]
                    elif transport == "wg" and slot:
                        node.update({"wg_ip": slot["ip"], "wg_pubkey": slot["pubkey"], "wg_privkey": slot["privkey"]})
                    st["fallback_node"] = node
                    log(f"baseline unavailable {int(unavailable_age)}s -> +1 fallback node {cid} via {transport}")

    fallback = st.get("fallback_node")
    if fallback and not fallback.get("llm_endpoint_set"):
        ip, port = instance_public_endpoint(fallback["contract"], LLM_PORT)
        if ip:
            url = f"http://{ip}:{port}/v1"
            set_llm_endpoint(url)
            fallback["llm_endpoint_set"] = True
            log(f"fallback LLM endpoint -> {url}")

    effective_baseline = 1 if baseline_ok or fallback else 0
    want = desired_nodes(depth_eff, st.get("low_since"), now, len(nodes), effective_baseline)

    if len(nodes) < want:
        restarted = False
        if REUSE and st.get("stopped"):
            node = st["stopped"].pop(0)
            if start_instance(node["contract"], dry_run):
                node["created_at"] = now
                nodes.append(node)
                registry_set(node["contract"], "running")
                restarted = True
                log(f"depth={depth_eff} want={want} -> restarted stopped node {node['contract']} (now {len(nodes)})")
            else:
                registry_remove(node["contract"])
        if not restarted:
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
                log(f"depth={depth_eff} want={want} -> +1 node {new} via {transport} (now {len(nodes)})")
        st["nodes"] = nodes
    elif len(nodes) > want:
        removable = [n for n in nodes if now - n["created_at"] >= MIN_UPTIME]
        burst_depth = r.llen(BURST_KEY)
        if removable and burst_depth > 0:
            removable = []
            hold_reason = f"burst={burst_depth} draining"
        elif removable and burst_running():
            removable = []
            hold_reason = "burst job running; hold for drain"
        else:
            hold_reason = "all < min_uptime"
        if not removable:
            log(f"depth={depth_eff} want={want} nodes={len(nodes)} {hold_reason}; hold")
        else:
            victim = max(removable, key=lambda n: n["created_at"])  # newest first
            if REUSE:
                stop_instance(victim["contract"], dry_run)
                registry_set(victim["contract"], "stopped")
                st.setdefault("stopped", []).insert(0, victim)
                while len(st["stopped"]) > KEEP_STOPPED:
                    old = st["stopped"].pop()
                    destroy_instance(old["contract"], dry_run)
                    if old.get("wg_pubkey") and not dry_run:
                        wg_remove_peer(old["wg_pubkey"])
                    registry_remove(old["contract"])
                log(f"depth={depth_eff} want={want} -> stopped node {victim['contract']} (now {len(nodes) - 1} hot)")
            else:
                destroy_instance(victim["contract"], dry_run)
                if victim.get("wg_pubkey") and not dry_run:
                    wg_remove_peer(victim["wg_pubkey"])
                registry_remove(victim["contract"])
            nodes.remove(victim)
            st["nodes"] = nodes
            log(f"depth={depth_eff} want={want} -> -1 node {victim['contract']} (now {len(nodes)})")

    training_tick(r, st, now, dry_run)
    return depth_eff


def queued_work_seconds(r) -> float:
    """R15: estimated GPU-seconds of queued work (duration x model class).

    Falls back to depth x DEFAULT_JOB_SECONDS when Redis lacks lrange or the DB
    is unreachable, so the depth-only behavior remains the safety net."""
    try:
        ids = []
        for key in (QUEUE_KEY, BURST_KEY):
            for item in r.lrange(key, 0, -1):
                ids.append(item.decode() if isinstance(item, bytes) else str(item))
        if not ids:
            return 0.0
        eng = _engine()
        if eng is None:
            return len(ids) * DEFAULT_JOB_SECONDS
        import sqlalchemy

        with eng.connect() as conn:
            rows = conn.execute(
                sqlalchemy.text(
                    "select request_json from jobs where id = any(:ids) "
                    "and status in ('queued','waiting_for_worker')"
                ),
                {"ids": ids},
            ).fetchall()
        total = 0.0
        for (rj,) in rows:
            rj = rj if isinstance(rj, dict) else json.loads(rj or "{}")
            adm = rj.get("_admission") or {}
            fam = adm.get("family") or "turbo"
            dur = float(rj.get("duration_seconds") or rj.get("duration") or 30)
            total += (WORK_BASE_SECONDS + WORK_SECONDS_PER_MINUTE * dur / 60.0) * FAMILY_FACTORS.get(fam, 1.0)
        total += max(0, len(ids) - len(rows)) * DEFAULT_JOB_SECONDS
        return total
    except Exception:
        return (r.llen(QUEUE_KEY) + r.llen(BURST_KEY)) * DEFAULT_JOB_SECONDS


def burst_running() -> bool:
    """True while a music.generate attempt runs on a non-baseline (burst) worker.

    Scale-down must not stop a node mid-job (R9); the queue-depth guard alone
    misses the node that is *executing* the last job.
    """
    eng = _engine()
    if eng is None:
        return False
    try:
        import sqlalchemy

        with eng.connect() as conn:
            n = conn.execute(
                sqlalchemy.text(
                    "select count(*) from job_attempts a join jobs j on j.id = a.job_id "
                    "where a.status='running' and j.operation='music.generate' "
                    "and a.worker_id is not null and a.worker_id not like 'oal-baseline%'"
                )
            ).scalar()
        return bool(n)
    except Exception:
        return False


def train_running() -> bool:
    """True while any UAIS voice job is claimed and running (best-effort)."""
    eng = _engine()
    if eng is None:
        return False
    try:
        import sqlalchemy

        with eng.connect() as conn:
            n = conn.execute(
                sqlalchemy.text(
                    "select count(*) from jobs where operation in "
                    "('voice.analyze','voice.train','voice.validate') and status='running'"
                )
            ).scalar()
        return bool(n)
    except Exception:
        return False


def _training_pool_tick(r, st, now, dry_run, pool):
    depth = r.llen(pool["queue"])
    nodes = st.get(pool["nodes"], [])
    stopped = st.get(pool["stopped"], [])
    if depth > 0:
        st[pool["idle"]] = None
        since = st.get(pool["pending"]) or now
        st[pool["pending"]] = since
        if len(nodes) < pool["max"] and now - since >= TRAIN_WAIT_LOCAL:
            while len(nodes) < pool["max"] and REUSE and stopped:
                node = stopped.pop(0)
                if start_instance(node["contract"], dry_run):
                    node["created_at"] = now
                    nodes.append(node)
                    registry_set(node["contract"], "running")
                    log(f"{pool['name']} pending={depth} -> restarted stopped training node {node['contract']}")
                else:
                    registry_remove(node["contract"])
            if len(nodes) < pool["max"]:
                last_created = st.get(pool["last"]) or 0
                if now - last_created >= TRAIN_CREATE_GUARD_SECONDS:
                    cid = create_instance(None, dry_run, VAST_TRANSPORT, role="training_worker",
                                          image=pool["image"], min_vram=pool["min_vram"],
                                          max_dph=pool["max_dph"], train_queue=pool["train_queue"])
                    if cid:
                        st[pool["last"]] = now
                        nodes.append({"contract": cid, "created_at": now, "transport": VAST_TRANSPORT})
                        log(f"{pool['name']} pending={depth} -> +1 training node {cid}")
                else:
                    log(f"{pool['name']} create guard active ({int(now - last_created)}s since last create)")
            st[pool["nodes"]] = nodes
    else:
        st[pool["pending"]] = None
        if train_running():
            st[pool["idle"]] = None
            return
        if nodes:
            idle = st.get(pool["idle"]) or now
            st[pool["idle"]] = idle
            if now - idle >= TRAIN_DOWN_SECONDS:
                for n in nodes:
                    stop_instance(n["contract"], dry_run)
                    registry_set(n["contract"], "stopped")
                    stopped.insert(0, n)
                st[pool["nodes"]] = []
                while len(stopped) > KEEP_STOPPED:
                    old = stopped.pop()
                    destroy_instance(old["contract"], dry_run)
                    registry_remove(old["contract"])
                st[pool["stopped"]] = stopped
                log(f"{pool['name']} idle -> stopped training node(s)")


def training_tick(r, st, now, dry_run=False):
    """Keep pool-sized Vast training nodes up while UAIS voice jobs are pending."""
    pools = [
        {"name": "train-2b", "queue": TRAIN_QUEUE, "max": TRAIN_MAX_NODES,
         "nodes": "train_nodes", "stopped": "train_stopped", "pending": "train_pending_since",
         "idle": "train_idle_since", "last": "train_last_created_at",
         "image": TRAIN_IMAGE or None, "min_vram": None, "max_dph": None,
         "train_queue": "training"},
        {"name": "train-xl", "queue": TRAIN_QUEUE_XL, "max": TRAIN_XL_MAX_NODES,
         "nodes": "train_xl_nodes", "stopped": "train_xl_stopped", "pending": "train_xl_pending_since",
         "idle": "train_xl_idle_since", "last": "train_xl_last_created_at",
         "image": TRAIN_IMAGE or None, "min_vram": TRAIN_XL_MIN_VRAM, "max_dph": TRAIN_XL_MAX_DPH,
         "train_queue": "training-xl"},
    ]
    for pool in pools:
        _training_pool_tick(r, st, now, dry_run, pool)


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
        f"max={MAX_NODES} baseline={BASELINE} baseline_id={BASELINE_WORKER_ID or '-'} "
        f"fallback_grace>{int(BASELINE_UNAVAILABLE_GRACE_SECONDS)}s restore>{int(BASELINE_RESTORE_GRACE_SECONDS)}s "
        f"to_one>{int(TO_ONE_SECONDS)}s down>{int(SCALE_DOWN_SECONDS)}s min_uptime={int(MIN_UPTIME)}s state={st}")
    last_reconcile = 0.0
    last_prune = 0.0
    while True:
        try:
            depth = tick(r, st, args.dry_run)
            if time.time() - last_reconcile >= RECONCILE_SECONDS:
                reconcile(st)
                last_reconcile = time.time()
            if time.time() - last_prune >= PRUNE_SECONDS:
                prune()
                last_prune = time.time()
            save_state(st)
        except Exception as e:
            log(f"tick error: {e}")
        if args.once:
            break
        time.sleep(POLL)


if __name__ == "__main__":
    main()
