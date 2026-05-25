import json
import os
import shutil


def process(input_path: str, output_path: str) -> dict:
    if os.path.exists(input_path):
        shutil.copy2(input_path, output_path)

    report = {
        "preset": "demo_draft",
        "integrated_lufs": -14.0,
        "true_peak_dbtp": -1.0,
        "dynamic_range_db": 8.0,
        "placeholder": True,
    }
    return report
