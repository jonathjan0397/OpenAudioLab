import os
from typing import Optional


class WaveformGenerator:
    @staticmethod
    def generate_peaks(audio_path: str, num_peaks: int = 200) -> Optional[dict]:
        try:
            import wave

            with wave.open(audio_path, "rb") as wf:
                sample_rate = wf.getframerate()
                num_frames = wf.getnframes()
                duration = num_frames / sample_rate if sample_rate > 0 else 0

            step = max(1, num_frames // num_peaks)
            peaks = []

            with wave.open(audio_path, "rb") as wf:
                for i in range(0, num_frames, step):
                    wf.setpos(i)
                    frame = wf.readframes(1)
                    if frame:
                        sample = int.from_bytes(frame[:2], byteorder="little", signed=True)
                        peaks.append(abs(sample) / 32768.0)

            while len(peaks) < num_peaks:
                peaks.append(0.0)

            return {
                "peaks": peaks[:num_peaks],
                "duration_seconds": round(duration, 2),
                "sample_rate": sample_rate,
                "num_peaks": len(peaks),
            }
        except Exception:
            return {
                "peaks": [0.0] * num_peaks,
                "duration_seconds": 15.0,
                "sample_rate": 44100,
                "num_peaks": num_peaks,
                "placeholder": True,
            }
