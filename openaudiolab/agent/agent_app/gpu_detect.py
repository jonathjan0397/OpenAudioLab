import logging

logger = logging.getLogger("worker.gpu_detect")


def detect_gpu() -> dict:
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram_bytes = torch.cuda.get_device_properties(0).total_memory
            vram_gb = round(vram_bytes / (1024 ** 3), 1)
            return {
                "available": True,
                "name": gpu_name,
                "vram_gb": vram_gb,
                "cuda_available": True,
            }
    except ImportError:
        pass

    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split(",")
            return {
                "available": True,
                "name": parts[0].strip(),
                "vram_gb": float(parts[1].strip()) / 1024,
                "cuda_available": True,
            }
    except Exception:
        pass

    return {
        "available": False,
        "name": None,
        "vram_gb": 0,
        "cuda_available": False,
    }
