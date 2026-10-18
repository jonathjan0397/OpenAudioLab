#!/usr/bin/env python3
"""Import the house-LoRA selection into the hub as a finalized dataset.

Phases: convert mp3->wav (parallel ffmpeg), create profile+dataset, upload
each wav via the upload-session API and attach as a dataset track with a
caption label, then finalize. Resumable via curation/import_state.json.
"""
import argparse
import concurrent.futures as cf
import json
import subprocess
import sys
import threading
from pathlib import Path

import httpx

CUR = Path("/Cold-Archive/OpenAudioLab/curation")
STATE = CUR / "import_state.json"
API = "http://192.151.156.124:50555/api/v1"
EMAIL = "jonathjan0397@gmail.com"
PASSWORD = "3671A113a05786!"


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"tracks": {}, "profile_id": None, "dataset_id": None, "version_id": None}


def save_state(state, lock):
    with lock:
        STATE.write_text(json.dumps(state))


def login() -> httpx.Client:
    client = httpx.Client(base_url=API, timeout=120.0)
    r = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    r.raise_for_status()
    return client


def caption(t):
    parts = [t["artist"], (t["genre"] or "").lower(), t["decade"]]
    parts += [m.lower() for m in (t.get("moods") or [])[:2]]
    parts += [s.lower() for s in (t.get("styles") or [])[:2]]
    return ", ".join(p for p in parts if p)


def convert_one(t, stage_dir):
    out = stage_dir / f"{t['key']}.wav"
    if out.exists() and out.stat().st_size > 100_000:
        return out
    tmp = out.with_suffix(".tmp.wav")
    for attempt in range(3):
        subprocess.run(
            ["ffmpeg", "-y", "-nostdin", "-loglevel", "error", "-i", t["path"],
             "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(tmp)],
            check=True, capture_output=True)
        if tmp.exists() and tmp.stat().st_size > 100_000:
            break
        import time as _t
        _t.sleep(2 * (attempt + 1))
    tmp.rename(out)
    return out


def upload_one(client, t, wav_path):
    r = client.post("/assets/uploads", json={"filename": wav_path.name, "content_type": "audio/wav"})
    r.raise_for_status()
    upload_id = r.json()["upload_id"]
    with wav_path.open("rb") as fh:
        r = client.put(f"/assets/uploads/{upload_id}/data", content=fh.read(),
                       headers={"Content-Type": "audio/wav"})
    r.raise_for_status()
    r = client.post(f"/assets/uploads/{upload_id}/complete")
    r.raise_for_status()
    asset_id = r.json()["asset"]["asset_id"]
    return asset_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--stage-dir", default="/Cold-Archive/house-wav")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-convert", action="store_true")
    args = ap.parse_args()

    tracks = [json.loads(l) for l in (CUR / "selection.jsonl").open()]
    for i, t in enumerate(tracks):
        t["key"] = f"t{i:05d}"
    if args.limit:
        tracks = tracks[:args.limit]
    stage_dir = Path(args.stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    state = load_state()
    lock = threading.Lock()

    if not args.skip_convert:
        def _bad_wav(t):
            entry = state["tracks"].get(t["key"], {})
            wav = entry.get("wav")
            return not wav or not Path(wav).exists() or Path(wav).stat().st_size <= 100_000
        todo = [t for t in tracks if _bad_wav(t)]
        print(f"convert: {len(todo)} of {len(tracks)}", flush=True)
        done = 0
        with cf.ThreadPoolExecutor(max_workers=8) as pool:
            futs = {pool.submit(convert_one, t, stage_dir): t for t in todo}
            for fut in cf.as_completed(futs):
                t = futs[fut]
                out = fut.result()
                with lock:
                    state["tracks"].setdefault(t["key"], {})["wav"] = str(out)
                done += 1
                if done % 100 == 0:
                    print(f"converted {done}/{len(todo)}", flush=True)
                    save_state(state, lock)
        save_state(state, lock)

    client = login()
    if not state["profile_id"]:
        r = client.post("/artist-profiles", json={"name": "House Style", "bio": "Curated house model trained on the OAL library."})
        r.raise_for_status()
        state["profile_id"] = r.json()["profile_id"]
        save_state(state, lock)
    if not state["dataset_id"]:
        r = client.post(f"/artist-profiles/{state['profile_id']}/datasets",
                        json={"name": "House Style v1"})
        r.raise_for_status()
        state["dataset_id"] = r.json()["dataset_id"]
        save_state(state, lock)
    print(f"profile={state['profile_id']} dataset={state['dataset_id']}", flush=True)

    todo = [t for t in tracks if "asset_id" not in state["tracks"].get(t["key"], {})]
    print(f"upload: {len(todo)} of {len(tracks)}", flush=True)
    errors = []
    done = 0

    def work(t):
        nonlocal client
        wav_path = Path(state["tracks"][t["key"]]["wav"])
        for attempt in range(4):
            try:
                asset_id = upload_one(client, t, wav_path)
                r = client.post(f"/datasets/{state['dataset_id']}/tracks",
                                json={"asset_id": asset_id, "labels": {"caption": caption(t)}})
                if not (r.status_code == 409 and "TRACK_DUPLICATE" in r.text):
                    r.raise_for_status()
                break
            except Exception:
                if attempt == 3:
                    raise
                import time as _t
                _t.sleep(5 * (attempt + 1))
                client = login()
        with lock:
            state["tracks"][t["key"]]["asset_id"] = asset_id

    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(work, t): t for t in todo}
        for fut in cf.as_completed(futs):
            t = futs[fut]
            try:
                fut.result()
            except Exception as exc:
                errors.append((t["key"], str(exc)[:200]))
            done += 1
            if done % 50 == 0 or done == len(todo):
                print(f"uploaded {done}/{len(todo)}", flush=True)
                save_state(state, lock)
    save_state(state, lock)
    print(f"errors: {len(errors)}", flush=True)
    for k, e in errors[:10]:
        print(" ", k, e)

    if not errors and not args.limit:
        r = client.post(f"/datasets/{state['dataset_id']}/finalize")
        print("finalize:", r.status_code, r.text[:300], flush=True)
        if r.status_code == 201:
            state["version_id"] = r.json().get("dataset_version_id") or r.json().get("version_id")
            save_state(state, lock)
            print("version:", state["version_id"])


if __name__ == "__main__":
    sys.exit(main())
