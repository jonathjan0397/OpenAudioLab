"""Advanced error logging for agent triage (M17).

Writes structured rows to the error_logs table so an agent can be handed a
self-contained brief (component, code, message, traceback, context, links).
"""

from __future__ import annotations

import traceback as _tb
from typing import Any

from .models import ErrorLog


def record_error(
    db,
    *,
    component: str,
    error_code: str,
    message: str,
    exc: BaseException | None = None,
    route: str | None = None,
    http_status: int | None = None,
    context: dict[str, Any] | None = None,
    job_id: str | None = None,
    worker_id: str | None = None,
    user_id: str | None = None,
) -> None:
    """Persist one error row. Never raises — logging must not break the caller."""
    try:
        tb = None
        if exc is not None:
            tb = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))[:8000]
        elif _tb.format_exc() not in ("", "None\n"):
            tb = _tb.format_exc()[:8000]
        fingerprint = f"{component}:{error_code}:{(route or '').split('?')[0]}"[:160]
        with db.session() as session:
            session.add(
                ErrorLog(
                    component=component,
                    route=route[:120] if route else None,
                    http_status=http_status,
                    error_code=error_code,
                    message=(message or "")[:4000],
                    traceback=tb,
                    context_json=_jsonable(context or {}),
                    job_id=job_id,
                    worker_id=worker_id,
                    user_id=user_id,
                    fingerprint=fingerprint,
                )
            )
            session.commit()
    except Exception:  # noqa: BLE001 - logging must never cascade
        pass


def _jsonable(obj: Any) -> Any:
    import json

    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return {k: str(v) for k, v in obj.items()} if isinstance(obj, dict) else str(obj)


def agent_brief(row: ErrorLog) -> str:
    """Compact markdown brief ready to paste into an agent prompt."""
    lines = [
        f"## {row.error_code} — {row.component}",
        f"- **when:** {row.created_at.isoformat() if row.created_at else '?'}",
        f"- **route:** {row.route or '-'} (HTTP {row.http_status or '-'})",
        f"- **message:** {row.message}",
    ]
    if row.job_id:
        lines.append(f"- **job:** {row.job_id}")
    if row.worker_id:
        lines.append(f"- **worker:** {row.worker_id}")
    if row.context_json:
        import json

        lines.append(f"- **context:** {json.dumps(row.context_json)[:1500]}")
    if row.traceback:
        lines.append("\n```\n" + row.traceback[-2000:] + "\n```")
    return "\n".join(lines)
