"""Internal worker endpoints (private; reached over the WireGuard tunnel).

The worker code bundle lets an ephemeral remote node pull the current
application code from the backend after it connects, so the heavy runtime base
image stays generic and code iteration never rebuilds it. The backend is the
source of truth for the worker code revision.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import Response

router = APIRouter()

APP_DIR = Path(__file__).resolve().parents[1]


def build_bundle(revision: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for path in sorted(APP_DIR.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tar.add(path, arcname=f"app/{path.relative_to(APP_DIR).as_posix()}")
        data = f"{revision}\n".encode("utf-8")
        info = tarfile.TarInfo("REVISION")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


@router.get("/worker/bundle")
def worker_bundle(request: Request) -> Response:
    revision = request.app.state.settings.build_revision
    body = build_bundle(revision)
    return Response(
        content=body,
        media_type="application/gzip",
        headers={
            "X-OAL-Revision": revision,
            "Content-Disposition": 'attachment; filename="oal-worker-bundle.tar.gz"',
        },
    )
