import json
import os
import zipfile


def create_zip(job_id: str, output_path: str, artifacts: dict, lyrics: dict, metadata: dict, logs: list) -> str:
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, path in artifacts.items():
            if os.path.exists(path):
                ext = os.path.splitext(name)[1]
                folder = "audio" if ext in (".wav", ".mp3") else "exports"
                zf.write(path, f"{folder}/{name}")

        for name, content in lyrics.items():
            zf.writestr(f"lyrics/{name}", content)

        for name, data in metadata.items():
            if isinstance(data, dict):
                zf.writestr(f"metadata/{name}", json.dumps(data, indent=2))
            elif isinstance(data, str) and os.path.exists(data):
                zf.write(data, f"metadata/{name}")

        log_text = "\n".join(f"[{e.get('timestamp', '')}] {e.get('stage', '')}: {e.get('message', '')}" for e in logs)
        zf.writestr("logs/pipeline_log.txt", log_text)

    return output_path
