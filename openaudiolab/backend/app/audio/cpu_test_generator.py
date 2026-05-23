import math
import os
import struct
import wave
from typing import Optional


class CPUTestAudioGenerator:
    SAMPLE_RATE = 44100
    BITS_PER_SAMPLE = 16
    NUM_CHANNELS = 2

    @staticmethod
    def generate_sine_wave(frequency: float, duration: float, amplitude: float = 0.3) -> bytes:
        num_samples = int(CPUTestAudioGenerator.SAMPLE_RATE * duration)
        samples = []
        for i in range(num_samples):
            t = i / CPUTestAudioGenerator.SAMPLE_RATE
            value = int(amplitude * 32767 * math.sin(2 * math.pi * frequency * t))
            value = max(-32768, min(32767, value))
            samples.append(value)

        raw = b""
        for s in samples:
            raw += struct.pack("<h", s)
            raw += struct.pack("<h", s)

        return raw

    @staticmethod
    def generate_chord(frequencies: list[float], duration: float, amplitude: float = 0.2) -> bytes:
        num_samples = int(CPUTestAudioGenerator.SAMPLE_RATE * duration)
        samples = []
        for i in range(num_samples):
            t = i / CPUTestAudioGenerator.SAMPLE_RATE
            value = sum(
                amplitude * math.sin(2 * math.pi * f * t)
                for f in frequencies
            )
            value = value / len(frequencies)
            value = int(value * 32767)
            value = max(-32768, min(32767, value))
            samples.append(value)

        raw = b""
        for s in samples:
            raw += struct.pack("<h", s)
            raw += struct.pack("<h", s)

        return raw

    @staticmethod
    def generate_test_audio(output_path: str, duration_seconds: float = 15.0) -> Optional[str]:
        try:
            max_duration = min(duration_seconds, 15.0)

            sections = [
                (261.63, 4.0),
                (293.66, 4.0),
                (329.63, 4.0),
                (349.23, max(1.0, max_duration - 12.0)),
            ]

            os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

            with wave.open(output_path, "w") as wav_file:
                wav_file.setnchannels(CPUTestAudioGenerator.NUM_CHANNELS)
                wav_file.setsampwidth(CPUTestAudioGenerator.BITS_PER_SAMPLE // 8)
                wav_file.setframerate(CPUTestAudioGenerator.SAMPLE_RATE)

                for freq, dur in sections:
                    if dur <= 0:
                        continue
                    audio_data = CPUTestAudioGenerator.generate_chord(
                        [freq, freq * 1.5, freq * 2.0],
                        dur,
                        amplitude=0.15,
                    )
                    wav_file.writeframes(audio_data)

            return output_path
        except Exception:
            return None
