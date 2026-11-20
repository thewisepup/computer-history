from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from computer_history.logs.config import LOG_BACKUPS, LOG_FILE_NAME, PACKAGE_LOGGER

LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40, "critical": 50}


def log_files(log_dir: Path) -> list[Path]:
    """The log file and its rotated copies that exist, oldest first."""
    names = [f"{LOG_FILE_NAME}.{n}" for n in range(LOG_BACKUPS, 0, -1)] + [LOG_FILE_NAME]
    return [log_dir / name for name in names if (log_dir / name).is_file()]


def read_records(
    log_dir: Path,
    *,
    since: datetime | None = None,
    level: str = "debug",
    run: str | None = None,
    logger: str | None = None,
) -> Iterator[dict[str, object]]:
    """The JSON records in the log folder, oldest first, that match every filter given.

    A line that is not a JSON object is skipped, and logger matches a dotted prefix.
    """
    floor = LEVELS[level]
    for path in log_files(log_dir):
        if since is not None and datetime.fromtimestamp(path.stat().st_mtime, UTC) < since:
            continue
        with path.open(encoding="utf-8", errors="replace") as lines:
            for line in lines:
                doc = _parse(line)
                if doc is None or LEVELS.get(str(doc.get("level")), 0) < floor:
                    continue
                if run is not None and doc.get("run") != run:
                    continue
                if logger is not None and not _under(str(doc.get("logger", "")), logger):
                    continue
                if since is not None and not _at_or_after(doc.get("ts"), since):
                    continue
                yield doc


def _parse(line: str) -> dict[str, object] | None:
    try:
        doc: object = json.loads(line)
    except ValueError:
        return None
    return cast("dict[str, object]", doc) if isinstance(doc, dict) else None


def _under(name: str, prefix: str) -> bool:
    short = name.removeprefix(f"{PACKAGE_LOGGER}.")
    return any(n == prefix or n.startswith(f"{prefix}.") for n in (name, short))


def _at_or_after(ts: object, since: datetime) -> bool:
    try:
        return datetime.fromisoformat(str(ts)) >= since
    except ValueError:
        return False
