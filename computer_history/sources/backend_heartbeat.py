from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__all__ = [
    "BackendHeartbeat",
    "backend_heartbeat_path",
    "read_backend_heartbeat",
    "write_backend_heartbeat",
]

BACKEND_HEARTBEAT_NAME = "backend-heartbeat.json"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackendHeartbeat:
    """When the backend last completed an ingest cycle, and whether that cycle succeeded."""

    cycle_at: datetime
    ok: bool


def backend_heartbeat_path(db_path: Path) -> Path:
    """The heartbeat file sits beside the database the backend writes."""
    return db_path.parent / BACKEND_HEARTBEAT_NAME


def write_backend_heartbeat(path: Path, cycle_at: datetime, ok: bool) -> None:
    """Replace the heartbeat with a cycle's time and result in one step, logging a failed write."""
    staged = path.with_name(f".{path.name}.new")
    try:
        staged.write_text(json.dumps({"cycle_at": cycle_at.isoformat(), "ok": ok}), "utf-8")
        os.replace(staged, path)
    except OSError as exc:
        log.warning("could not write the backend heartbeat %s: %s", path, exc)


def read_backend_heartbeat(path: Path) -> BackendHeartbeat | None:
    """The last heartbeat, or None when none was written."""
    if not path.exists():
        return None
    written = json.loads(path.read_text(encoding="utf-8"))
    try:
        cycle_at = datetime.fromisoformat(written["cycle_at"])
        ok = written["ok"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{path} is not a heartbeat") from exc
    if cycle_at.tzinfo is None or not isinstance(ok, bool):
        raise ValueError(f"{path} is not a heartbeat")
    return BackendHeartbeat(cycle_at, ok)
