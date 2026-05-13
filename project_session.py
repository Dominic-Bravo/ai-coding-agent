"""Per-project session memory under <project>/.micro-agent/ (isolated per folder)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SESSION_VERSION = 1
SESSION_DIRNAME = ".micro-agent"
SESSION_FILENAME = "session.json"


def session_file_path(project_root: Path) -> Path:
    return project_root.resolve() / SESSION_DIRNAME / SESSION_FILENAME


def clear_session(project_root: Path) -> None:
    p = session_file_path(project_root)
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


def load_session(project_root: Path) -> dict[str, Any] | None:
    """
    Load session JSON if present, valid version, and project_root matches this folder.
    Returns None if missing, corrupt, or wrong project (e.g. copied file).
    """
    path = session_file_path(project_root)
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") != SESSION_VERSION:
        return None
    try:
        saved = Path(data["project_root"]).resolve()
        current = project_root.resolve()
    except (KeyError, OSError, TypeError):
        return None
    if saved != current:
        return None
    return data


def save_session(
    project_root: Path,
    *,
    user_request: str,
    plan: str,
    dom_summary: str,
    tasks: list[str],
    artifacts: list[dict[str, str]],
    status: str,
) -> None:
    """Write checkpoint; status is 'in_progress' or 'completed'."""
    path = session_file_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": SESSION_VERSION,
        "project_root": str(project_root.resolve()),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "user_request": user_request,
        "plan": plan,
        "dom_summary": dom_summary,
        "tasks": tasks,
        "artifacts": artifacts,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def artifacts_to_payload(artifacts: list[Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for a in artifacts:
        out.append({"task": a.task, "code": a.code, "review": a.review})
    return out
