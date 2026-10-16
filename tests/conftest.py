from __future__ import annotations

import os
import pathlib
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="oal-tests-"))
_DB = _TMP / "test.db"
os.environ["OAL_DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["OAL_CORS_ORIGINS"] = "https://openaudiolab.io,http://localhost:3000"
os.environ["OAL_STORAGE_DIR"] = str(_TMP / "artifacts")
os.environ["OAL_SECRET_KEY"] = "test-secret"
os.environ["OAL_SSE_FOLLOW_SECONDS"] = "0.3"
os.environ["OAL_FIXTURE_LATENCY_SECONDS"] = "0.01"
os.environ["OAL_WORKER_BRPOP_TIMEOUT_SECONDS"] = "1"
os.environ["OAL_ENGINE_POLL_SECONDS"] = "0.05"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.main import create_app  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def _migrate() -> None:
    cfg = AlembicConfig(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def _clean(_migrate) -> None:
    from app.db import Db

    db = Db(os.environ["OAL_DATABASE_URL"])
    with db.session() as session:
        for table in (
            "jobs",
            "idempotency_records",
            "job_attempts",
            "job_events",
            "outbox_records",
            "assets",
            "workers",
            "projects",
            "project_versions",
            "upload_sessions",
            "artist_profiles",
            "rights_records",
            "datasets",
            "dataset_tracks",
            "dataset_versions",
            "artist_profile_versions",
            "training_runs",
            "evaluations",
            "loras",
            "users",
            "user_sessions",
            "site_settings",
            "favorites",
            "credit_entries",
        ):
            session.execute(text(f"DELETE FROM {table}"))
        session.commit()


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def orch():
    """Direct orchestration access (fakeredis-backed) for pipeline tests."""
    import fakeredis

    from app.config import get_settings
    from app.db import Db
    from app.orchestration import Dispatcher
    from app.queue import RedisQueue
    from app.storage import LocalObjectStorage
    from app.worker import FixtureWorker

    settings = get_settings()
    db = Db(settings.database_url)
    queue = RedisQueue(fakeredis.FakeStrictRedis())
    storage = LocalObjectStorage(settings.storage_dir)
    dispatcher = Dispatcher(db, queue, settings)
    worker = FixtureWorker(db, queue, storage, settings, worker_id="test-fixture")
    return type("Orch", (), {"db": db, "queue": queue, "storage": storage, "settings": settings, "dispatcher": dispatcher, "worker": worker})()


TOKEN_A = "Bearer user-a-secret-token"
TOKEN_B = "Bearer user-b-secret-token"


def auth(token: str = TOKEN_A, **headers: str) -> dict[str, str]:
    return {"Authorization": token, **headers}


def submit_body(**overrides) -> dict:
    body = {
        "operation": "music.generate",
        "model_id": "ace-step-1.5",
        "music_description": "Acoustic country, warm baritone.",
        "lyrics": "[Verse]\nMorning settles on the pine\n",
        "lyrics_origin": "frontend_llm",
        "instrumental": False,
        "outputs": ["mix_wav", "mix_mp3"],
    }
    body.update(overrides)
    return body


def submit(client: TestClient, token: str = TOKEN_A, key: str = "k1", **overrides) -> "object":
    headers = auth(token, **{"Idempotency-Key": key})
    return client.post("/api/v1/jobs", json=submit_body(**overrides), headers=headers)
