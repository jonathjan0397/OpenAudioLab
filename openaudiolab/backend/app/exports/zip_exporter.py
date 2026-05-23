import json
import os
import zipfile
from typing import Optional


class ZIPExporter:
    @staticmethod
    def create_export(
        job_id: str,
        output_path: str,
        artifacts: dict,
        metadata: dict,
        lyrics: dict,
        logs: list[dict],
    ) -> Optional[str]:
        try:
            os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                if "audio" in artifacts:
                    for name, path in artifacts["audio"].items():
                        if os.path.exists(path):
                            zf.write(path, f"audio/{name}")

                if lyrics:
                    for name, content in lyrics.items():
                        zf.writestr(f"lyrics/{name}", content)

                if metadata:
                    for name, data in metadata.items():
                        if isinstance(data, str) and os.path.exists(data):
                            zf.write(data, f"metadata/{name}")
                        else:
                            zf.writestr(f"metadata/{name}", json.dumps(data, indent=2))

                if logs:
                    log_text = "\n".join(
                        f"[{entry.get('timestamp', '')}] {entry.get('stage', '')}: {entry.get('message', '')}"
                        for entry in logs
                    )
                    zf.writestr("logs/pipeline_log.txt", log_text)

                file_manifest = {
                    "job_id": job_id,
                    "files": [],
                }
                for name in artifacts.get("audio", {}):
                    file_manifest["files"].append({"path": f"audio/{name}", "type": "audio"})
                for name in lyrics:
                    file_manifest["files"].append({"path": f"lyrics/{name}", "type": "lyrics"})
                zf.writestr("metadata/file_manifest.json", json.dumps(file_manifest, indent=2))

            return output_path
        except Exception:
            return None

    @staticmethod
    def create_stub_export(job_id: str, output_path: str) -> Optional[str]:
        try:
            os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

            with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("audio/draft.wav", "STUB_AUDIO")
                zf.writestr("audio/final_master.wav", "STUB_MASTER")
                zf.writestr("lyrics/lyrics_original_ai.txt", "Stub lyrics")
                zf.writestr("metadata/job.json", json.dumps({"job_id": job_id, "status": "completed"}, indent=2))
                zf.writestr("metadata/composition_plan.json", json.dumps({
                    "bpm": 92,
                    "key": "D minor",
                    "duration_seconds": 15,
                    "sections": [{"name": "Test", "duration": 15, "description": "CPU test"}],
                    "instruments": ["synth"],
                }, indent=2))
                zf.writestr("logs/pipeline_log.txt", "Pipeline log stub")
                zf.writestr("metadata/file_manifest.json", json.dumps({
                    "job_id": job_id,
                    "files": [
                        {"path": "audio/draft.wav", "type": "audio"},
                        {"path": "audio/final_master.wav", "type": "audio"},
                        {"path": "lyrics/lyrics_original_ai.txt", "type": "lyrics"},
                    ],
                }, indent=2))

            return output_path
        except Exception:
            return None
