import os
import shutil


def process_audio(input_path: str, output_path: str) -> str:
    if os.path.exists(input_path):
        shutil.copy2(input_path, output_path)
        return output_path
    return input_path
