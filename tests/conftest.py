from __future__ import annotations

import os
import pathlib
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="oal-tests-"))
_DB = _TMP / "test.db"
os.environ["OAL_DATABASE_URL"] = f"sqlite:///{_DB}"
os.environ["OAL_CORS_ORIGINS"] = "https://openaudiolab.io,http://localhost:3000"

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
        session.execute(text("DELETE FROM jobs"))
        session.execute(text("DELETE FROM idempotency_records"))
        session.commit()


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(create_app())


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
