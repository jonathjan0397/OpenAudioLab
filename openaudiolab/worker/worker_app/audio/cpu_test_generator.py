import math
import struct
import wave
import os


def generate_test_audio(output_path: str, duration: float = 15.0) -> str:
    sample_rate = 44100
    num_samples = int(sample_rate * duration)

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    with wave.open(output_path, "w") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        for i in range(num_samples):
            t = i / sample_rate
            freq = 261.63 + (i / num_samples) * 130.81
            value = int(0.2 * 32767 * math.sin(2 * math.pi * freq * t))
            value = max(-32768, min(32767, value))
            frame = struct.pack("<hh", value, value)
            wav_file.writeframes(frame)

    return output_path
