#!/usr/bin/env python3
"""Queue the four house-LoRA training variants against the finalized dataset."""
import json
import sys

import httpx

API = "http://192.151.156.124:50555/api/v1"
EMAIL = "jonathjan0397@gmail.com"
PASSWORD = "3671A113a05786!"
STATE = "/Cold-Archive/OpenAudioLab/curation/import_state.json"

VARIANTS = [
    {"name": "baseline", "hyperparams": {"lora_rank": 64, "lora_alpha": 128, "learning_rate": 1e-4, "train_epochs": 20}},
    {"name": "small-fast", "hyperparams": {"lora_rank": 32, "lora_alpha": 64, "learning_rate": 2e-4, "train_epochs": 20}},
    {"name": "deep", "hyperparams": {"lora_rank": 64, "lora_alpha": 128, "learning_rate": 2e-4, "train_epochs": 30}},
    {"name": "wide", "hyperparams": {"lora_rank": 128, "lora_alpha": 256, "learning_rate": 1e-4, "train_epochs": 20}},
]


def main():
    state = json.load(open(STATE))
    profile_id, version_id = state["profile_id"], state["version_id"]
    if not version_id:
        print("dataset not finalized yet (version_id missing)")
        return 1
    client = httpx.Client(base_url=API, timeout=60.0)
    client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}).raise_for_status()
    for v in VARIANTS:
        hp = dict(v["hyperparams"])
        epochs = hp.pop("train_epochs")
        body = {
            "profile_id": profile_id,
            "dataset_version_id": version_id,
            "budget": {"max_epochs": epochs, "max_wall_seconds": 21600},
            "hyperparams": hp | {"train_epochs": epochs},
            "seed": 42,
        }
        r = client.post("/trainings", json=body)
        ok = r.status_code == 202
        print(f"{v['name']:12s} {r.status_code} {r.json().get('job_id', r.text[:160])}")
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
