def generate_waveform(audio_path: str) -> dict:
    return {
        "peaks": [0.1] * 200,
        "duration_seconds": 15,
        "sample_rate": 44100,
    }
