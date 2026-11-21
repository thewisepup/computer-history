from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from computer_history.logs.config import LEVEL_NAMES, LOG_BACKUPS, LOG_FILE_NAME, PACKAGE_LOGGER

LEVELS = {name.lower(): logging.getLevelNamesMapping()[name] for name in LEVEL_NAMES}


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

    A line without a JSON object and an ISO time is skipped; logger matches a dotted prefix.
    """
    floor = LEVELS[level]
    for path in log_files(log_dir):
        try:
            for doc in _records(path, since):
                if LEVELS.get(str(doc.get("level")), 0) < floor:
                    continue
                if run is not None and doc.get("run") != run:
                    continue
                if logger is not None and not _under(str(doc.get("logger", "")), logger):
                    continue
                yield doc
        except FileNotFoundError:
            continue


def _records(path: Path, since: datetime | None) -> Iterator[dict[str, object]]:
    if since is not None and datetime.fromtimestamp(path.stat().st_mtime, UTC) < since:
        return
    with path.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            doc = _parse(line)
            at = None if doc is None else _time(doc.get("ts"))
            if doc is not None and at is not None and (since is None or at >= since):
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


def _time(ts: object) -> datetime | None:
    if not isinstance(ts, str):
        return None
    try:
        at = datetime.fromisoformat(ts)
    except ValueError:
        return None
    return at if at.tzinfo is not None else None
