#!/usr/bin/env python3
"""Pinned Model Lab trainer: one frozen dataset -> LoRA adapter.

Drives the documented ACE-Step training REST surface end to end
(dataset scan -> preprocess -> train -> export) and prints a single JSON
result line for the worker:

  {"artifact_key", "sha256", "hours", "spend_usd", "export_path", "name"}

Runs inside the worker container (code bundle at /srv/openaudiolab/code).
Audio paths come from the frozen dataset manifest and must be reachable
from the worker (TrueNAS is mounted at the same path on hub and workers).

Environment: OAL_ML_ATTEMPT_ID (required), OAL_ML_EPOCHS (default 6),
OAL_ML_SEED (default 2026); everything else from OAL_* settings.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

def _fail(message: str) -> int:
    print(json.dumps({"ok": False, "error": message}), file=sys.stderr)
    return 1


def main() -> int:
    attempt_id = (sys.argv[1] if len(sys.argv) > 1 else "").strip() \
        or __import__("os").environ.get("OAL_ML_ATTEMPT_ID", "").strip()
    if not attempt_id:
        return _fail("OAL_ML_ATTEMPT_ID not set")

    from .config import get_settings
    from .db import Db
    from .engine_acestep import EngineError, RequestsTransport
    from .models import MlDataset, MlTrainingAttempt
    from .training_acestep import AceStepTrainingAdapter

    settings = get_settings()
    db = Db(settings.database_url)
    with db.session() as session:
        attempt = session.get(MlTrainingAttempt, attempt_id)
        if attempt is None:
            return _fail(f"unknown attempt: {attempt_id}")
        dataset = session.get(MlDataset, attempt.dataset_id)
        if dataset is None:
            return _fail("dataset record missing")
        entries = (dataset.manifest_json or {}).get("entries", [])
        paths = [e["path"] for e in entries]
        name = dataset.name
    if not paths:
        return _fail("dataset manifest has no entries")
    missing = [p for p in paths if not Path(p).is_file()]
    if missing:
        return _fail(f"audio not reachable from worker: {len(missing)} of {len(paths)} "
                     f"(first: {missing[0]})")

    work = Path(settings.train_workdir) / f"ml-{attempt_id[:8]}"
    audio = work / "audio"
    shutil.rmtree(work, ignore_errors=True)
    audio.mkdir(parents=True)
    for entry in entries:
        src = Path(entry["path"])
        shutil.copy2(src, audio / f"{entry['sha256'][:6]}-{src.name}")

    transport = RequestsTransport(settings.acestep_base_url,
                                  settings.acestep_api_key or None,
                                  timeout=settings.train_http_timeout_seconds)
    adapter = AceStepTrainingAdapter(transport)
    deadline = time.monotonic() + max(0.1, settings.model_lab_run_wall_hours) * 3600.0

    def remaining() -> float:
        return deadline - time.monotonic()

    while True:  # engine may be idle-stopped; wait for readiness
        try:
            adapter.ensure_model(settings.acestep_model)
            break
        except EngineError:
            if remaining() <= 0:
                return _fail("engine never became ready")
            time.sleep(5)

    try:
        adapter.scan_dataset(str(audio), f"ml-{attempt_id[:8]}")
        tensors = work / "tensors"
        adapter.preprocess(str(tensors))
        lora_dir = work / "lora"
        epochs = int(__import__("os").environ.get("OAL_ML_EPOCHS", "6"))
        seed = int(__import__("os").environ.get("OAL_ML_SEED", "2026"))
        started = time.monotonic()
        adapter.start_training(str(tensors), str(lora_dir), epochs, seed)
        while True:
            status = adapter.training_status()
            if not status.get("is_training", False):
                break
            if remaining() <= 0:
                adapter.stop_training()
                return _fail("TRAINING_TIMEOUT (wall deadline)")
            time.sleep(10)
        export = work / "export"
        adapter.export(str(lora_dir), str(export))
    except EngineError as exc:
        return _fail(f"engine training error: {exc}")

    artifacts = sorted(export.rglob("*.safetensors"))
    if not artifacts:
        return _fail("ARTIFACT_INVALID: export produced no safetensors file")
    artifact = artifacts[0]
    sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    hours = round((time.monotonic() - started) / 3600.0, 4)
    print(json.dumps({"artifact_key": "pending", "sha256": sha, "hours": hours,
                      "spend_usd": 0.0, "export_path": str(artifact),
                      "name": f"{name}-adapter"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
