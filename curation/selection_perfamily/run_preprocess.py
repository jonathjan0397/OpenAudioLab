import os, json
from acestep.training_v2.preprocess import preprocess_audio_files

r = preprocess_audio_files(
    audio_dir=None,
    output_dir=os.environ.get("OUT", "/work/tensors_rock"),
    checkpoint_dir=os.environ.get("CKPT", "/opt/acestep/checkpoints"),
    variant=os.environ.get("VARIANT", "turbo"),
    max_duration=float(os.environ.get("MAXDUR", "240")),
    dataset_json=os.environ.get("DJ", "/work/rock_dataset.json"),
    device="cuda:0",
)
print("PREPROCESS_RESULT", json.dumps(r), flush=True)
