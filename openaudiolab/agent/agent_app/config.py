import os

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
AGENT_REGISTRATION_TOKEN = os.environ.get("AGENT_REGISTRATION_TOKEN", "")
AGENT_NAME = os.environ.get("AGENT_NAME", "local-agent")
AGENT_MODE = os.environ.get("AGENT_MODE", "lite")
MODEL_PACK_PATH = os.environ.get("MODEL_PACK_PATH", "/app/model-packs/model-pack-lite.json")
AGENT_VERSION = os.environ.get("AGENT_VERSION", "0.1.0")
ENABLE_CPU_TEST_GENERATION = os.environ.get("ENABLE_CPU_TEST_GENERATION", "true").lower() == "true"
CPU_TEST_MAX_DURATION_SECONDS = int(os.environ.get("CPU_TEST_MAX_DURATION_SECONDS", "15"))
HEARTBEAT_INTERVAL = int(os.environ.get("HEARTBEAT_INTERVAL", "15"))
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "5"))
