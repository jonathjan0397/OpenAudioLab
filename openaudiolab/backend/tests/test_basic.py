import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.1.0-foundation"


def test_setup_status():
    response = client.get("/api/setup/status")
    assert response.status_code == 200
    data = response.json()
    assert "setup_completed" in data
    assert "initial_admin_created" in data


def test_setup_initialize():
    response = client.post("/api/setup/initialize", json={
        "admin_email": "test@example.com",
        "admin_password": "SecurePassword123!",
        "confirm_password": "SecurePassword123!",
        "site_name": "Test Site",
        "public_backend_url": "http://localhost:8000",
        "storage_provider": "local",
        "default_retention_days": 7,
        "enable_cpu_test_mode": True,
        "ENABLE_CLOUD_AGENTS": False,
    })
    assert response.status_code == 200
    data = response.json()
    assert "AGENT_REGISTRATION_TOKEN" in data


def test_login():
    client.post("/api/setup/initialize", json={
        "admin_email": "test@example.com",
        "admin_password": "SecurePassword123!",
        "confirm_password": "SecurePassword123!",
        "site_name": "Test Site",
        "public_backend_url": "http://localhost:8000",
        "storage_provider": "local",
        "default_retention_days": 7,
        "enable_cpu_test_mode": True,
        "ENABLE_CLOUD_AGENTS": False,
    })
    response = client.post("/api/auth/login", json={
        "email": "test@example.com",
        "password": "SecurePassword123!",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


def test_worker_registration_rejects_invalid_token():
    response = client.post("/api/workers/register", json={
        "worker_name": "test-worker",
        "AGENT_MODE": "lite",
        "registration_token": "invalid-token",
    })
    data = response.json()
    assert data["accepted"] is False


def test_lyric_structure_validation():
    from app.lyrics.structure_validator import LyricStructureValidator

    result = LyricStructureValidator.validate("[Verse 1]\nLine one\nLine two\n\n[Chorus]\nHook line")
    assert result["valid"] is True
    assert result["section_count"] == 2


def test_lyric_reasoning_returns_structured_report():
    from app.lyrics.reasoning import LyricReasoning

    lyrics = "[Verse 1]\nTest lyrics here\n\n[Chorus]\nThis is the hook"
    result = LyricReasoning.analyze(lyrics, "test prompt", "rock", "energetic")
    assert "passed" in result
    assert "score" in result
    assert "mode" in result
    assert "issues" in result
    assert "recommended_action" in result


def test_zip_exporter_creates_zip():
    import tempfile
    import os
    from app.exports.zip_exporter import ZIPExporter

    with tempfile.TemporaryDirectory() as tmpdir:
        zip_path = os.path.join(tmpdir, "test.zip")
        result = ZIPExporter.create_stub_export("test-job-123", zip_path)
        assert result is not None
        assert os.path.exists(zip_path)
