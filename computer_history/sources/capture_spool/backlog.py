from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from computer_history.sources.capture_spool.record import (
    WINDOW_TEXT_KINDS,
    InvalidRecord,
    parse_record,
)
from computer_history.sources.capture_spool.spool import (
    FINISHED_NAME_FORMAT,
    OPEN_FILE,
    UNREADABLE_FOLDER,
    SpoolError,
    finished_files,
    read_lines,
)


@dataclass(frozen=True)
class SpoolBacklog:
    """What the spool holds: finished files waiting, when the oldest was finished, files set aside.

    It also says whether any record is not yet stored, and the time and kind of the newest one.
    """

    waiting: int
    oldest_finished_at: datetime | None
    unreadable: int
    unstored: bool
    newest: tuple[datetime, str] | None


def spool_backlog(folder: Path) -> SpoolBacklog:
    """Count the spool's waiting and set-aside files and find its newest record; none if absent."""
    waiting = finished_files(folder)
    open_file = folder / OPEN_FILE
    try:
        open_has_records = _has_bytes(open_file)
        newest = next(
            (
                found
                for path in (open_file, *reversed(waiting))
                if (found := _newest_record(path)) is not None
            ),
            None,
        )
        unreadable = _count_files(folder / UNREADABLE_FOLDER)
    except OSError as exc:
        raise SpoolError(f"cannot inspect the spool at {folder}: {exc}") from exc
    return SpoolBacklog(
        waiting=len(waiting),
        oldest_finished_at=_finished_at(waiting[0]) if waiting else None,
        unreadable=unreadable,
        unstored=bool(waiting) or open_has_records,
        newest=newest,
    )


def _newest_record(path: Path) -> tuple[datetime, str] | None:
    try:
        lines = read_lines(path)
    except FileNotFoundError:
        return None
    for raw in reversed(lines):
        try:
            record = parse_record(raw.decode("utf-8"))
        except (UnicodeDecodeError, InvalidRecord):
            continue
        if record.kind in WINDOW_TEXT_KINDS:
            return record.captured_at, record.kind
    return None


def _has_bytes(path: Path) -> bool:
    try:
        return path.stat().st_size > 0
    except FileNotFoundError:
        return False


def _finished_at(path: Path) -> datetime | None:
    try:
        return datetime.strptime(path.stem, FINISHED_NAME_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        pass
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except FileNotFoundError:
        return None


def _count_files(folder: Path) -> int:
    try:
        with os.scandir(folder) as entries:
            return sum(
                entry.is_file(follow_symlinks=False) and not entry.name.startswith(".")
                for entry in entries
            )
    except FileNotFoundError:
        return 0
