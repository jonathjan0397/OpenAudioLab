#!/usr/bin/env python3
"""Standalone house-LoRA trainer runner (hub side).

Rents a Vast GPU node running stratastack/acestep-train (baked house-agent),
watches the hub-side marker files the agent rsyncs back, collects the PEFT
adapter, and destroys the node. Completely independent of the OAL queue/DB:
stdlib only, no redis, no sqlalchemy. Must run on the hub (marker files are
local paths under HOUSE_STORAGE).

    scripts/house_train.py offers --model turbo
    scripts/house_train.py run --model turbo
    scripts/house_train.py run --model xl_turbo --epochs 20
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import time
from pathlib import Path

HOME = Path.home()
VASTAI = os.environ.get("HOUSE_VASTAI", str(HOME / "OpenAudioLab/.venv/bin/vastai"))
IMAGE = os.environ.get("HOUSE_IMAGE", "stratastack/acestep-train:v1")
IMAGE_GB = float(os.environ.get("HOUSE_IMAGE_GB", "36"))
HUB_SSH = os.environ.get("HOUSE_SSH_TARGET", "administrator@192.151.156.124")
STORAGE = os.environ.get("HOUSE_STORAGE", "/srv/oal-storage/house-lora")
TENSOR_TAR = os.environ.get("HOUSE_TENSOR_TAR", STORAGE + "/tensors-0c372dba.tar.zst")
TENSOR_GB = float(os.environ.get("HOUSE_TENSOR_GB", "10.5"))
DISK = os.environ.get("HOUSE_DISK", "60")
MAX_DPH = float(os.environ.get("HOUSE_MAX_DPH", "0.25"))  # accepted hourly ceiling
MIN_RELIABILITY = float(os.environ.get("HOUSE_MIN_RELIABILITY", "0.95"))
DEPLOY_KEY = Path(os.environ.get("HOUSE_DEPLOY_KEY", str(HOME / ".ssh/oal_worker_deploy")))
COOLDOWN_FILE = Path(os.environ.get("HOUSE_COOLDOWN", str(HOME / ".house_train_cooldown.json")))
COOLDOWN_MIN = 45
# Boot + image pull + export/rsync-back overhead on top of pure train time.
OVERHEAD_H = 0.5

MODELS = {
    "turbo": {"name": "acestep-v15-turbo", "min_per_epoch": 14, "grad_ckpt": "0"},
    "xl_turbo": {"name": "acestep-v15-xl-turbo", "min_per_epoch": 32, "grad_ckpt": "1"},
}
# Rough training throughput vs RTX 3090 (offer ranking only, not a whitelist).
SPEED = {
    "3090": 1.0, "3080": 0.85, "4080": 1.15, "4090": 1.35, "5080": 1.4,
    "5090": 1.8, "a100": 1.3, "h100": 2.2, "v100s": 0.5, "v100": 0.45,
    "a6000": 0.8, "rtx 8000": 0.8, "l40s": 1.0, "l20": 0.9,
    "rtx 6000 ada": 1.3, "rtx pro 6000": 1.6,
}


def log(msg: str) -> None:
    print(f"[house-train] {time.strftime('%m-%d %H:%M:%S')} {msg}", flush=True)


def sh(cmd: list[str]) -> tuple[int, str, str]:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def speed_of(gpu_name: str) -> float:
    g = (gpu_name or "").lower()
    for k, v in SPEED.items():
        if k in g:
            return v
    return 0.8


def load_cooldown() -> dict[str, float]:
    try:
        return {k: float(v) for k, v in json.loads(COOLDOWN_FILE.read_text()).items()}
    except Exception:
        return {}


def save_cooldown(cd: dict[str, float]) -> None:
    try:
        COOLDOWN_FILE.write_text(json.dumps(cd))
    except Exception as exc:
        log(f"cooldown save failed: {exc}")


def rank_offers(model: str, epochs: int, cd: dict[str, float]) -> list[dict]:
    _, out, _ = sh([
        VASTAI, "search", "offers",
        "gpu_ram>=24 num_gpus=1 rentable=true cuda_max_good>=12.8 verification=verified",
        "--raw", "-o", "dph_total", "--limit", "200",
    ])
    try:
        offers = json.loads(out)
    except Exception:
        log("offer search returned no JSON")
        return []
    m = MODELS[model]
    now = time.time()
    ranked = []
    for o in offers:
        if cd.get(str(o.get("id")), 0) > now:
            continue
        geo = str(o.get("geolocation", ""))
        rel = o.get("reliability2") or 0
        dph = o.get("dph_total") or 0
        down = o.get("inet_down") or 0
        if not (geo.endswith(", US") or geo.endswith(", CA")):
            continue
        if rel < MIN_RELIABILITY or dph <= 0 or down <= 0:
            continue
        if dph > MAX_DPH:
            continue
        if (o.get("disk_space") or 0) < int(DISK) + 30:
            continue
        # Estimated total run cost: pull (image+tensors at inet_down, 50% eff)
        # + train (model epochs at GPU-relative speed) + fixed overhead.
        pull_h = (IMAGE_GB + TENSOR_GB) / (down * 0.225)
        train_h = epochs * m["min_per_epoch"] / 60 / speed_of(o.get("gpu_name", ""))
        est_cost = dph * (pull_h + train_h + OVERHEAD_H)
        ranked.append({"offer": o, "pull_h": pull_h, "train_h": train_h,
                       "est_cost": est_cost})
    ranked.sort(key=lambda r: r["est_cost"])
    return ranked


def create_instance(offer_id: int, run_id: str, model: str, args) -> int | None:
    m = MODELS[model]
    key_b64 = base64.b64encode(DEPLOY_KEY.read_bytes()).decode()
    env = " ".join([
        f"-e HOUSE_MODEL={m['name']}",
        f"-e HOUSE_RUN_ID={run_id}",
        f"-e HOUSE_SSH_TARGET={HUB_SSH}",
        f"-e HOUSE_REMOTE_DIR={STORAGE}/{run_id}",
        f"-e HOUSE_TENSOR_TAR={TENSOR_TAR}",
        f"-e HOUSE_EPOCHS={args.epochs}",
        f"-e HOUSE_RANK={args.rank}",
        f"-e HOUSE_ALPHA={args.alpha}",
        f"-e HOUSE_LR={args.lr}",
        f"-e HOUSE_SEED={args.seed}",
        f"-e HOUSE_GRAD_CKPT={m['grad_ckpt']}",
        f"-e HOUSE_MAX_HOURS={args.wall_hours}",
        f"-e OAL_PUSH_PRIVKEY_B64={key_b64}",
    ])
    _, out, err = sh([VASTAI, "create", "instance", str(offer_id),
                      "--image", IMAGE, "--disk", DISK,
                      "--label", f"house-{run_id}", "--env", env,
                      "--args", "run"])
    cid = None
    match = re.search(r"'new_contract':\s*(\d+)", out)
    if match:
        cid = int(match.group(1))
    log(f"create offer={offer_id} contract={cid} out={out.strip()[:160]}")
    if cid is None:
        log(f"create stderr={err.strip()[:200]}")
    return cid


def destroy_instance(cid: int) -> None:
    sh([VASTAI, "destroy", "instance", str(cid), "-y"])
    log(f"destroyed {cid}")


def instance_alive(cid: int) -> bool:
    _, out, _ = sh([VASTAI, "show", "instance", str(cid), "--raw"])
    try:
        d = json.loads(out)
        if isinstance(d, dict):
            items = d.get("instances") or ([d] if d.get("actual_status") else [])
        else:
            items = d
        st = items[0].get("actual_status", "")
    except Exception:
        return False
    return st in ("running", "loading", "scheduling", "starting", "resetting",
                  "recovering", "measuring")


def poll_run(remote: Path, cid: int, wall_hours: float) -> tuple[bool, str]:
    start = time.time()
    last_note = 0.0
    while True:
        fail_file = remote / "FAIL"
        if fail_file.exists():
            return False, fail_file.read_text().strip()[:300]
        if (remote / "DONE").exists():
            return True, "done"
        elapsed = time.time() - start
        if elapsed > wall_hours * 3600:
            return False, f"wall clock {wall_hours}h exceeded"
        # A node that left the live states (destroyed/offered/lost) will never
        # write markers; fail fast instead of burning the whole wall clock.
        if elapsed > 900 and not instance_alive(cid):
            return False, f"instance {cid} left live states"
        if elapsed - last_note > 300:
            last_note = elapsed
            try:
                d = json.loads((remote / "status.json").read_text()).get("data") or {}
                log(f"  [{cid}] ep {d.get('current_epoch')}/{d.get('train_epochs', '?')} "
                    f"loss={d.get('current_loss')} eta={d.get('estimated_time_remaining')}")
            except Exception:
                log(f"  [{cid}] no status yet ({int(elapsed // 60)}m)")
        time.sleep(60)


def cmd_offers(args) -> int:
    ranked = rank_offers(args.model, args.epochs, load_cooldown())
    if not ranked:
        log("no eligible offers")
        return 1
    for r in ranked[:10]:
        o = r["offer"]
        log(f"offer {o.get('id')} {o.get('gpu_name')} {o.get('gpu_uuid', '')[:0]}"
            f"{o.get('geolocation')} dph=${o.get('dph_total'):.3f} "
            f"inet={o.get('inet_down')} rel={o.get('reliability2')} "
            f"pull={r['pull_h']:.1f}h train={r['train_h']:.1f}h "
            f"est=${r['est_cost']:.2f}")
    return 0


def cmd_run(args) -> int:
    model = args.model
    run_id = args.run_id or f"house-v1-{model}"
    remote = Path(STORAGE) / run_id
    remote.mkdir(parents=True, exist_ok=True)

    def clean_markers():
        for marker in ("DONE", "FAIL", "status.json", "api.log"):
            try:
                (remote / marker).unlink()
            except FileNotFoundError:
                pass
        subprocess.run(["rm", "-rf", str(remote / "adapter")], check=False)

    clean_markers()
    cd = load_cooldown()
    attempts = 0
    while attempts < args.max_attempts:
        attempts += 1
        clean_markers()
        ranked = rank_offers(model, args.epochs, cd)
        if not ranked:
            log(f"attempt {attempts}: no eligible offers; waiting 10min")
            time.sleep(600)
            continue
        top = ranked[0]
        o = top["offer"]
        log(f"attempt {attempts}: offer {o.get('id')} {o.get('gpu_name')} "
            f"{o.get('geolocation')} dph=${o.get('dph_total'):.3f} "
            f"est=${top['est_cost']:.2f} (pull {top['pull_h']:.1f}h + "
            f"train {top['train_h']:.1f}h)")
        cid = create_instance(o["id"], run_id, model, args)
        if cid is None:
            cd[str(o["id"])] = time.time() + COOLDOWN_MIN * 60
            save_cooldown(cd)
            continue
        ok, reason = poll_run(remote, cid, args.wall_hours)
        destroy_instance(cid)
        if ok:
            adapter = remote / "adapter"
            if not (adapter / "adapter_config.json").exists():
                log(f"DONE but adapter missing under {adapter}")
                return 1
            log(f"SUCCESS: adapter at {adapter}")
            return 0
        log(f"attempt {attempts} failed: {reason}")
        cd[str(o["id"])] = time.time() + COOLDOWN_MIN * 60
        save_cooldown(cd)
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("offers", "run"):
        sp = sub.add_parser(name)
        sp.add_argument("--model", required=True, choices=sorted(MODELS))
        sp.add_argument("--epochs", type=int, default=20)
        if name == "run":
            sp.add_argument("--run-id", default=None)
            sp.add_argument("--rank", type=int, default=64)
            sp.add_argument("--alpha", type=int, default=128)
            sp.add_argument("--lr", default="1e-4")
            sp.add_argument("--seed", type=int, default=42)
            sp.add_argument("--wall-hours", type=float, default=24)
            sp.add_argument("--max-attempts", type=int, default=3)
    args = ap.parse_args()
    return cmd_offers(args) if args.cmd == "offers" else cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
