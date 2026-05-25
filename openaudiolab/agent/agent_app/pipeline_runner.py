import json
import logging
import os
import tempfile
import time

import requests

from agent_app.audio.cpu_test_generator import CPUTestAudioGenerator
from agent_app.config import BACKEND_URL, CPU_TEST_MAX_DURATION_SECONDS, ENABLE_CPU_TEST_GENERATION
from agent_app.stages import lyrics as lyrics_stage
from agent_app.stages import lyric_structure_validation as structure_stage
from agent_app.stages import lyric_reasoning as reasoning_stage
from agent_app.stages import humanization as humanization_stage
from agent_app.stages import composition as composition_stage
from agent_app.stages import generation as generation_stage
from agent_app.stages import daw as daw_stage
from agent_app.stages import effects as effects_stage
from agent_app.stages import mastering as mastering_stage
from agent_app.stages import export as export_stage
from agent_app.storage.upload_client import StorageUploadClient

logger = logging.getLogger("worker.pipeline")


class PipelineRunner:
    def __init__(self, job_id: str, request: dict, worker_api_token: str):
        self.job_id = job_id
        self.request = request
        self.worker_api_token = worker_api_token
        self.temp_dir = tempfile.mkdtemp(prefix=f"job_{job_id}_")
        self.pipeline_log = []

    def run(self) -> bool:
        try:
            pipeline = self.request.get("pipeline", [])
            if not pipeline:
                pipeline = [
                    "job_intake", "prompt_validation", "lyrics_generation_or_ingestion",
                    "lyrics_structure_validation", "lyrics_reasoning", "lyrics_revision",
                    "lyrics_humanization", "composition_planning", "audio_generation",
                    "daw_processing", "effects_processing", "mastering",
                    "preview_waveform_generation", "zip_export", "storage_upload",
                    "signed_download_url", "retention_cleanup",
                ]

            artifacts = {}
            lyrics_content = {}
            metadata = {}

            for stage_name in pipeline:
                if stage_name == "job_intake":
                    continue

                self._update_stage(stage_name, "running")
                self._log(stage_name, f"Starting stage: {stage_name}")

                try:
                    result = self._execute_stage(stage_name, artifacts, lyrics_content, metadata)

                    if result.get("skipped"):
                        self._update_stage(stage_name, "skipped", metadata=result.get("metadata"))
                        self._log(stage_name, f"Skipped: {result.get('reason', '')}")
                    elif result.get("success"):
                        self._update_stage(stage_name, "completed", metadata=result.get("metadata"))
                        artifacts.update(result.get("artifacts", {}))
                        lyrics_content.update(result.get("lyrics", {}))
                        metadata.update(result.get("metadata", {}))
                        self._log(stage_name, "Completed")
                    else:
                        self._update_stage(stage_name, "failed", error=result.get("error"))
                        self._log(stage_name, f"Failed: {result.get('error')}")
                        return False

                except Exception as e:
                    self._update_stage(stage_name, "failed", error=str(e))
                    self._log(stage_name, f"Error: {str(e)}")
                    return False

                time.sleep(0.3)

            self._log("pipeline", "All stages completed")
            return True

        finally:
            self._save_pipeline_log()

    def _execute_stage(self, stage_name: str, artifacts: dict, lyrics_content: dict, metadata: dict) -> dict:
        lyrics_mode = self.request.get("lyrics_mode", "ai")
        instrumental = self.request.get("instrumental", False)

        if stage_name == "prompt_validation":
            return {"success": True, "metadata": {"prompt_length": len(self.request.get("prompt", ""))}}

        elif stage_name == "lyrics_generation_or_ingestion":
            if instrumental or lyrics_mode == "instrumental":
                return {"skipped": True, "reason": "Instrumental mode"}
            if lyrics_mode == "provided":
                provided = self.request.get("provided_lyrics", "")
                lyrics_content["user_provided_lyrics.txt"] = provided
                return {"success": True, "lyrics": lyrics_content, "metadata": {"mode": "provided"}}
            if lyrics_mode == "ai":
                generated = lyrics_stage.generate(self.request)
                lyrics_content["lyrics_original_ai.txt"] = generated
                return {"success": True, "lyrics": lyrics_content, "metadata": {"mode": "ai"}}
            if lyrics_mode == "hybrid":
                provided = self.request.get("provided_lyrics", "")
                generated = lyrics_stage.generate_hybrid(self.request, provided)
                lyrics_content["lyrics_original_ai.txt"] = generated
                return {"success": True, "lyrics": lyrics_content, "metadata": {"mode": "hybrid"}}
            return {"success": True, "metadata": {"mode": lyrics_mode}}

        elif stage_name == "lyrics_structure_validation":
            all_lyrics = "\n".join(lyrics_content.values()) if lyrics_content else ""
            if not all_lyrics and lyrics_mode != "instrumental":
                return {"skipped": True, "reason": "No lyrics to validate"}
            result = structure_stage.validate(all_lyrics)
            lyrics_content["lyrics_structure_report.json"] = json.dumps(result, indent=2)
            return {"success": True, "metadata": result}

        elif stage_name == "lyrics_reasoning":
            if lyrics_mode not in ("ai", "hybrid"):
                return {"skipped": True, "reason": f"Not required for {lyrics_mode} mode"}
            all_lyrics = lyrics_content.get("lyrics_original_ai.txt", "")
            result = reasoning_stage.analyze(all_lyrics, self.request)
            lyrics_content["lyrics_quality_report.json"] = json.dumps(result, indent=2)
            return {"success": True, "metadata": result}

        elif stage_name == "lyrics_revision":
            if lyrics_mode not in ("ai", "hybrid"):
                return {"skipped": True, "reason": "Not required for this mode"}
            return {"success": True, "metadata": {"revisions": 0}}

        elif stage_name == "lyrics_humanization":
            if lyrics_mode not in ("ai", "hybrid"):
                return {"skipped": True, "reason": "Custom lyrics preserved exactly"}
            all_lyrics = "\n".join(lyrics_content.values()) if lyrics_content else ""
            humanized = humanization_stage.humanize(all_lyrics)
            lyrics_content["lyrics_humanized.txt"] = humanized
            return {"success": True, "lyrics": {"lyrics_humanized.txt": humanized}}

        elif stage_name == "composition_planning":
            plan = composition_stage.plan(self.request)
            metadata["composition_plan.json"] = plan
            return {"success": True, "metadata": {"composition_plan.json": plan}}

        elif stage_name == "audio_generation":
            draft_path = os.path.join(self.temp_dir, "draft.wav")
            duration = min(self.request.get("duration_seconds", 15), CPU_TEST_MAX_DURATION_SECONDS)
            if ENABLE_CPU_TEST_GENERATION:
                CPUTestAudioGenerator.generate_test_audio(draft_path, duration)
                artifacts["draft.wav"] = draft_path
                return {"success": True, "artifacts": {"draft.wav": draft_path}}
            return {"success": True, "metadata": {"cpu_test_stub": True}}

        elif stage_name == "daw_processing":
            draft_path = artifacts.get("draft.wav", "")
            if draft_path and os.path.exists(draft_path):
                processed = daw_stage.process(draft_path, os.path.join(self.temp_dir, "daw_processed.wav"))
                if processed:
                    artifacts["daw_processed.wav"] = processed
                    return {"success": True, "artifacts": {"daw_processed.wav": processed}}
            return {"success": True, "metadata": {"daw_stub": True}}

        elif stage_name == "effects_processing":
            input_path = artifacts.get("daw_processed.wav", artifacts.get("draft.wav", ""))
            if input_path and os.path.exists(input_path):
                processed = effects_stage.process(input_path, os.path.join(self.temp_dir, "effects_processed.wav"))
                if processed:
                    artifacts["effects_processed.wav"] = processed
                    return {"success": True, "artifacts": {"effects_processed.wav": processed}}
            return {"success": True, "metadata": {"effects_stub": True}}

        elif stage_name == "mastering":
            input_path = artifacts.get("effects_processed.wav", artifacts.get("daw_processed.wav", artifacts.get("draft.wav", "")))
            output_path = os.path.join(self.temp_dir, "final_master.wav")
            if input_path and os.path.exists(input_path):
                result = mastering_stage.process(input_path, output_path)
                if result:
                    artifacts["final_master.wav"] = output_path
                    return {"success": True, "artifacts": {"final_master.wav": output_path}, "metadata": result}
            return {"success": True, "metadata": {"mastering_stub": True}}

        elif stage_name == "preview_waveform_generation":
            audio_path = artifacts.get("final_master.wav", artifacts.get("draft.wav", ""))
            if audio_path and os.path.exists(audio_path):
                waveform_data = generation_stage.generate_waveform(audio_path)
                metadata["waveform.json"] = waveform_data
                return {"success": True, "metadata": {"waveform.json": waveform_data}}
            return {"success": True, "metadata": {"waveform_stub": True}}

        elif stage_name == "zip_export":
            zip_path = os.path.join(self.temp_dir, "final.zip")
            result = export_stage.create_zip(self.job_id, zip_path, artifacts, lyrics_content, metadata, self.pipeline_log)
            if result:
                artifacts["final.zip"] = zip_path
                return {"success": True, "artifacts": {"final.zip": zip_path}}
            return {"success": True, "metadata": {"zip_stub": True}}

        elif stage_name == "storage_upload":
            upload_client = StorageUploadClient(self.worker_api_token)
            for name, path in artifacts.items():
                if os.path.exists(path):
                    remote_key = f"/jobs/{self.job_id}/{'audio' if '.wav' in name or '.mp3' in name else 'exports'}/{name}"
                    upload_client.upload(path, remote_key)
            for name, content in lyrics_content.items():
                remote_key = f"/jobs/{self.job_id}/lyrics/{name}"
                upload_client.upload_content(content, remote_key)
            for name, data in metadata.items():
                remote_key = f"/jobs/{self.job_id}/metadata/{name}"
                if isinstance(data, str) and os.path.exists(data):
                    upload_client.upload(data, remote_key)
                else:
                    upload_client.upload_content(json.dumps(data, indent=2) if isinstance(data, dict) else str(data), remote_key)
            return {"success": True, "metadata": {"uploaded": True}}

        elif stage_name in ("signed_download_url", "retention_cleanup"):
            return {"success": True, "metadata": {}}

        return {"success": True, "metadata": {}}

    def _update_stage(self, stage_name: str, status: str, metadata: dict = None, error: str = None):
        try:
            requests.post(
                f"{BACKEND_URL}/api/agents/jobs/{self.job_id}/stage-update",
                json={"stage_name": stage_name, "status": status, "metadata": metadata, "error_message": error},
                headers={"X-Worker-Token": self.worker_api_token},
                timeout=10,
            )
        except Exception:
            pass

    def _log(self, stage: str, message: str):
        from datetime import datetime, timezone
        self.pipeline_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "level": "info",
            "message": message,
        })

    def _save_pipeline_log(self):
        log_path = os.path.join(self.temp_dir, "pipeline.log")
        with open(log_path, "w") as f:
            for entry in self.pipeline_log:
                f.write(f"[{entry['timestamp']}] {entry['stage']}: {entry['message']}\n")
