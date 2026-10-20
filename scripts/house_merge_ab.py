#!/usr/bin/env python3
"""Merge house LoRAs into ACE-Step checkpoints and generate A/B clips."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path


def http_json(method: str, url: str, payload=None, timeout: int = 120):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def log(message: str) -> None:
    print(f"[house-merge-ab] {message}", flush=True)


def discover_adapters(adapter_root: Path) -> list[Path]:
    adapters = []
    for path in sorted(adapter_root.glob("house-v1-*")):
        candidate = path / "adapter"
        if (candidate / "adapter_config.json").exists():
            adapters.append(candidate)
    return adapters


def copy_auxiliary_files(base_checkpoint: Path, out_path: Path) -> None:
    for src in base_checkpoint.iterdir():
        if not src.is_file():
            continue
        if src.name.startswith("model") and src.suffix == ".safetensors":
            continue
        if src.name == "model.safetensors.index.json":
            continue
        shutil.copy2(src, out_path / src.name)


def merge_one(
    base_checkpoint: Path,
    adapters: list[Path],
    scale: float,
    out_path: Path,
    combination_type: str = "cat",
    normalize_weights: bool = True,
) -> None:
    import torch
    from peft import PeftModel
    from transformers import AutoModel

    if out_path.exists():
        shutil.rmtree(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    log(f"loading base model {base_checkpoint}")
    model = AutoModel.from_pretrained(
        str(base_checkpoint),
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
    )
    decoder = model.decoder
    names: list[str] = []
    peft_model = None

    for idx, adapter in enumerate(adapters):
        name = f"house{idx:02d}"
        if idx == 0:
            peft_model = PeftModel.from_pretrained(
                decoder,
                str(adapter),
                adapter_name=name,
                is_trainable=False,
            )
        else:
            peft_model.load_adapter(str(adapter), adapter_name=name)
        names.append(name)

    weights = [float(scale)] * len(names)
    if normalize_weights:
        weights = [weight / len(names) for weight in weights]

    log(
        f"adding weighted adapter scale={scale} adapters={len(names)} "
        f"combination={combination_type} normalized={normalize_weights}"
    )
    peft_model.base_model.add_weighted_adapter(
        names,
        weights,
        "house",
        combination_type=combination_type,
    )
    peft_model.set_adapter("house")
    merged_decoder = peft_model.base_model.merge_and_unload(
        safe_merge=True,
        adapter_names=["house"],
    )
    model.decoder = merged_decoder

    log(f"saving merged checkpoint {out_path}")
    model.save_pretrained(str(out_path), safe_serialization=True)
    copy_auxiliary_files(base_checkpoint, out_path)

    del model
    del peft_model
    del merged_decoder
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def wait_api(api: str, timeout_seconds: int = 600) -> None:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        try:
            http_json("GET", f"{api}/health", timeout=10)
            return
        except Exception as exc:
            last_error = str(exc)
            time.sleep(5)
    raise RuntimeError(f"API did not become healthy: {last_error}")


def init_model(api: str, model_name: str) -> None:
    resp = http_json("POST", f"{api}/v1/init", {"model": model_name}, timeout=600)
    if resp.get("code") != 200:
        raise RuntimeError(f"model init failed: {resp}")


def submit_generate(api: str, model_name: str, prompt: dict) -> dict:
    payload = {
        "prompt": prompt["prompt"],
        "lyrics": "",
        "audio_format": "wav",
        "batch_size": 1,
        "thinking": False,
        "use_format": False,
        "model": model_name,
        "use_random_seed": False,
        "seed": int(prompt.get("seed", 42)),
        "audio_duration": float(prompt.get("duration_seconds", 30)),
        "use_cot_caption": False,
        "use_cot_language": False,
    }
    if prompt.get("instrumental", True):
        payload["instrumental"] = True
    resp = http_json("POST", f"{api}/release_task", payload, timeout=120)
    if resp.get("code") != 200:
        raise RuntimeError(f"release_task failed: {resp}")
    task_id = (resp.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError(f"release_task returned no task_id: {resp}")

    deadline = time.time() + 900
    while time.time() < deadline:
        query = http_json("POST", f"{api}/query_result", {"task_id_list": [task_id]}, timeout=60)
        entries = query.get("data") or []
        if not entries:
            raise RuntimeError(f"unknown task {task_id}: {query}")
        entry = entries[0]
        status = entry.get("status")
        if status == 1:
            raw = entry.get("result")
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            items = parsed if isinstance(parsed, list) else [parsed]
            file_url = next((item.get("file") for item in items if item.get("file")), None)
            if not file_url:
                raise RuntimeError(f"task {task_id} returned no file: {parsed}")
            return {"task_id": task_id, "file_url": file_url, "result": items[0]}
        if status == 2:
            raise RuntimeError(f"task {task_id} failed: {entry.get('error') or entry}")
        time.sleep(3)
    raise RuntimeError(f"task {task_id} timed out")


def download_file(api: str, file_url: str, out_path: Path) -> None:
    url = file_url if file_url.startswith("http") else f"{api}{file_url}"
    with urllib.request.urlopen(url, timeout=120) as resp:
        out_path.write_bytes(resp.read())


def generate_one(api: str, model_name: str, prompts: list[dict], out_dir: Path) -> list[dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for prompt in prompts:
        prompt_id = prompt["id"]
        out_path = out_dir / f"{prompt_id}.wav"
        log(f"generating {model_name}/{prompt_id}")
        result = submit_generate(api, model_name, prompt)
        download_file(api, result["file_url"], out_path)
        records.append(
            {
                "variant": model_name,
                "prompt_id": prompt_id,
                "prompt": prompt["prompt"],
                "duration_seconds": prompt.get("duration_seconds", 30),
                "seed": prompt.get("seed", 42),
                "instrumental": bool(prompt.get("instrumental", True)),
                "task_id": result["task_id"],
                "file": str(out_path),
                "engine_result": result["result"],
            }
        )
    return records


def cmd_merge(args: argparse.Namespace) -> None:
    adapters = discover_adapters(Path(args.adapter_root))
    if not adapters:
        raise RuntimeError(f"no adapters found under {args.adapter_root}")
    log(f"found {len(adapters)} adapters")
    scales = [float(s.strip()) for s in args.scales.split(",") if s.strip()]
    base_checkpoint = Path(args.base_checkpoint)
    for scale in scales:
        name = f"{args.variant_prefix}{int(round(scale * 100)):03d}"
        out_path = Path(args.checkpoint_root) / f"acestep-v15-{name}"
        merge_one(
            base_checkpoint,
            adapters,
            scale,
            out_path,
            combination_type=args.combination_type,
            normalize_weights=not args.raw_weights,
        )


def cmd_generate(args: argparse.Namespace) -> None:
    prompts = json.loads(Path(args.prompts).read_text(encoding="utf-8"))
    api = args.api.rstrip("/")
    wait_api(api)
    init_model(api, args.model)
    out_dir = Path(args.output_dir) / args.variant
    records = generate_one(api, args.model, prompts, out_dir)
    metadata_path = Path(args.metadata)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    existing = []
    if metadata_path.exists():
        existing = json.loads(metadata_path.read_text(encoding="utf-8"))
    existing.extend(records)
    metadata_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    merge = sub.add_parser("merge")
    merge.add_argument("--base-checkpoint", required=True)
    merge.add_argument("--adapter-root", required=True)
    merge.add_argument("--checkpoint-root", required=True)
    merge.add_argument("--variant-prefix", default="house_")
    merge.add_argument("--scales", default="0.30,0.50,0.70")
    merge.add_argument("--combination-type", default="cat")
    merge.add_argument("--raw-weights", action="store_true")
    merge.set_defaults(func=cmd_merge)

    generate = sub.add_parser("generate")
    generate.add_argument("--api", default="http://127.0.0.1:8001")
    generate.add_argument("--model", required=True)
    generate.add_argument("--variant", required=True)
    generate.add_argument("--prompts", required=True)
    generate.add_argument("--output-dir", required=True)
    generate.add_argument("--metadata", required=True)
    generate.set_defaults(func=cmd_generate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
