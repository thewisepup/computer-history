from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from computer_history.sources.runner import CycleSummary

__all__ = [
    "BACKEND_HEARTBEAT_NAME",
    "BackendHeartbeat",
    "backend_heartbeat_path",
    "read_backend_heartbeat",
    "write_backend_heartbeat",
]

BACKEND_HEARTBEAT_NAME = "backend-heartbeat.json"


@dataclass(frozen=True)
class BackendHeartbeat:
    """When the backend last completed an ingest cycle, and whether that cycle succeeded."""

    cycle_at: datetime
    ok: bool


def backend_heartbeat_path(db_path: Path) -> Path:
    """The heartbeat file sits beside the database the backend writes."""
    return db_path.parent / BACKEND_HEARTBEAT_NAME


def write_backend_heartbeat(path: Path, summary: CycleSummary) -> None:
    """Replace the heartbeat with this cycle's time and result, in one step."""
    staged = path.with_name(f".{path.name}.new")
    staged.write_text(
        json.dumps({"cycle_at": summary.at.isoformat(), "ok": summary.ok}), encoding="utf-8"
    )
    os.replace(staged, path)


def read_backend_heartbeat(path: Path) -> BackendHeartbeat | None:
    """The last heartbeat, or None when none was written; raises ValueError when unreadable."""
    try:
        written = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    try:
        return BackendHeartbeat(
            datetime.fromisoformat(str(written["cycle_at"])), bool(written["ok"])
        )
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{path} is not a heartbeat") from exc
