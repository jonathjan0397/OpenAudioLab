"""Remote-worker deployment pieces: S3 storage, code bundle, adapter portability."""

from __future__ import annotations

import hashlib
import io
import tarfile
from pathlib import Path

from app.config import get_settings
from app.storage import LocalObjectStorage, S3ObjectStorage, build_storage


def test_build_storage_defaults_local():
    settings = get_settings().model_copy(update={"storage_backend": "local", "storage_dir": "/tmp/oal-x"})
    assert isinstance(build_storage(settings), LocalObjectStorage)


def test_build_storage_s3_selected():
    from moto import mock_aws

    with mock_aws():
        settings = get_settings().model_copy(
            update={"storage_backend": "s3", "s3_bucket": "oal", "s3_region": "us-east-1"}
        )
        assert isinstance(build_storage(settings), S3ObjectStorage)


def test_s3_adapter_roundtrip_and_range():
    import boto3
    from moto import mock_aws

    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="oal")
        s3 = S3ObjectStorage(bucket="oal", region="us-east-1")
        body = b"hello world"
        assert s3.put("owners/o1/a.wav", body) == hashlib.sha256(body).hexdigest()
        assert s3.exists("owners/o1/a.wav")
        assert s3.get("owners/o1/a.wav").body == body
        ranged = s3.get("owners/o1/a.wav", (0, 4))
        assert ranged.body == b"hello"
        assert ranged.content_range == "bytes 0-4/11"
        s3.delete("owners/o1/a.wav")
        assert not s3.exists("owners/o1/a.wav")


def test_s3_adapter_prefix_isolation():
    import boto3
    from moto import mock_aws

    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="oal")
        s3 = S3ObjectStorage(bucket="oal", region="us-east-1", prefix="tenants/acme/")
        s3.put("k", b"v")
        raw = boto3.client("s3", region_name="us-east-1")
        keys = [o["Key"] for o in raw.list_objects_v2(Bucket="oal").get("Contents", [])]
        assert keys == ["tenants/acme/k"]


def test_worker_bundle_endpoint(client):
    response = client.get("/internal/v1/worker/bundle")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/gzip"
    assert "X-OAL-Revision" in response.headers
    with tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz") as tar:
        names = tar.getnames()
    assert "REVISION" in names
    assert "app/main.py" in names
    assert "app/storage.py" in names


def test_materialize_adapter_from_storage(tmp_path):
    from app.engine_worker import EngineWorker

    settings = get_settings().model_copy(update={"adapter_cache_dir": str(tmp_path / "cache")})
    storage = LocalObjectStorage(tmp_path / "store")
    storage.put("owners/o1/adapters/v1/adapter_config.json", b"{}")
    storage.put("owners/o1/adapters/v1/adapter_model.safetensors", b"bin")
    worker = EngineWorker(db=None, queue=None, storage=storage, adapter=None, settings=settings)
    artifacts = {
        "adapter_object_prefix": "owners/o1/adapters/v1",
        "adapter_files": ["adapter_config.json", "adapter_model.safetensors"],
    }
    path = worker._materialize_adapter(artifacts)
    assert Path(path).name == "v1"
    assert (Path(path) / "adapter_config.json").read_bytes() == b"{}"
    assert (Path(path) / "adapter_model.safetensors").read_bytes() == b"bin"
    assert worker._materialize_adapter({"adapter_path": "/x/y"}) == "/x/y"
    assert worker._materialize_adapter({}) is None
