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
        dest_name = f"{entry['sha256'][:6]}-{src.name}"
        dest = audio / dest_name
        shutil.copy2(src, dest)
        # ACE-Step training needs a per-sample label. The loader strips the
        # audio extension first, so the caption must be <stem>.caption.txt
        # (not <name>.mp3.caption.txt).
        caption = (entry.get("caption") or src.stem or "untitled").strip()
        dest.with_suffix("").with_name(dest.stem + ".caption.txt").write_text(
            caption + "\n", encoding="utf-8")

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
        status: dict = {}
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
    steps = int(status.get("current_step") or status.get("global_step") or 0)

    # Acceptance gate (ARTIST_TRAINING): real optimization steps, loadable
    # artifact, and at least one actual inference with the candidate loaded.
    if steps <= 0:
        return _fail(f"TRAINING_NO_PROGRESS: steps={steps}")
    try:
        from safetensors import safe_open

        with safe_open(str(artifact), framework="pt") as handle:
            tensors_count = len(list(handle.keys()))
    except Exception as exc:
        return _fail(f"ARTIFACT_INVALID: not loadable ({type(exc).__name__}: {exc})")
    if tensors_count <= 0:
        return _fail("ARTIFACT_INVALID: zero tensors")

    acceptance = {"steps": steps, "final_status": {k: status.get(k) for k in
                                                   ("current_epoch", "loss", "train_loss")
                                                   if status.get(k) is not None},
                  "loadable": True, "tensors": tensors_count}
    sample = work / "acceptance_sample.mp3"
    try:
        from .engine_acestep import AceStepAdapter

        gen = AceStepAdapter(transport, model=settings.acestep_model)
        adapter.load_lora(str(artifact))
        acceptance["lora_load"] = True
        first_caption = next((e.get("caption") for e in entries if e.get("caption")),
                             "instrumental acceptance test")
        payload = gen.build_payload(music_description=f"{first_caption}, acceptance test",
                                    lyrics=None, instrumental=True, seed=seed,
                                    duration_seconds=15, thinking=False)
        submit = gen.submit(payload)
        deadline2 = time.monotonic() + 420.0
        state, items = "pending", None
        while state == "pending" and time.monotonic() < deadline2:
            time.sleep(5)
            state, items = gen.poll(submit.task_id)
        if state != "succeeded" or not items:
            return _fail(f"ACCEPTANCE_INFERENCE_FAILED: {state} {gen.last_error}")
        audio_url = next((i.get("file") or i.get("audio_url") for i in items
                          if i.get("file") or i.get("audio_url")), None)
        if not audio_url:
            return _fail("ACCEPTANCE_INFERENCE_FAILED: no audio url in result")
        body = gen.download(audio_url)
        if len(body) < 1000:
            return _fail(f"ACCEPTANCE_INFERENCE_FAILED: tiny audio ({len(body)} bytes)")
        sample.write_bytes(body)
        acceptance.update({"inference_task": submit.task_id, "inference_bytes": len(body),
                           "inference_sha256": hashlib.sha256(body).hexdigest(),
                           "sample_path": str(sample)})
    except EngineError as exc:
        return _fail(f"ACCEPTANCE_ENGINE_ERROR: {exc}")
    finally:
        try:
            adapter.unload_lora()
        except Exception:
            pass

    print(json.dumps({"artifact_key": "pending", "sha256": sha, "hours": hours,
                      "spend_usd": 0.0, "export_path": str(artifact),
                      "steps": steps, "acceptance": acceptance,
                      "name": f"{name}-adapter"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
