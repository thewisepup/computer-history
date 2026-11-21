from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path

from computer_history.host import Host, HostError
from computer_history.stable.launch_agents import BACKEND, start_agent, stop_agent
from computer_history.stable.layout import Layout
from computer_history.store import (
    DatabaseCopy,
    DatabaseExists,
    Profile,
    backup_database,
    restore_database,
)

BACKUPS_FOLDER_NAME = "backups"
DAILY_FOLDER_NAME = "daily"
PRE_UPDATE_FOLDER_NAME = "pre-update"
SET_ASIDE_FOLDER_NAME = "set-aside"
TAKEN_AT_STAMP = "%Y-%m-%dT%H%M%S"
NOTHING_CHANGED = "nothing was changed"
RESTORE_FAILURES = (OSError, sqlite3.Error, RuntimeError)
DAILY_KEPT = 7
DAILY_NAME = re.compile(r"^history-(\d{4}-\d{2}-\d{2})\.db$")


def backups_folder(database: Path) -> Path:
    """Where a database's backups are kept: a folder beside it."""
    return database.parent / BACKUPS_FOLDER_NAME


def daily_backup_path(database: Path, day: date) -> Path:
    return _daily_folder(database) / f"history-{day.isoformat()}.db"


def _daily_folder(database: Path) -> Path:
    return backups_folder(database) / DAILY_FOLDER_NAME


@dataclass(frozen=True)
class DailyBackup:
    """Today's backup: the copy when this run took it, None when it was taken already."""

    path: Path
    copy: DatabaseCopy | None
    removed: tuple[Path, ...]


def take_daily_backup(database: Path, today: date) -> DailyBackup:
    """Copy the database into today's daily backup unless there is one, then drop the oldest days.

    The copy is checked for integrity before it is kept, and the newest seven days stay.
    """
    target = daily_backup_path(database, today)
    copy = None
    if not target.exists():
        try:
            copy = backup_database(database, target)
        except DatabaseExists:
            pass
    return DailyBackup(target, copy, _drop_oldest(database))


def take_pre_update_backup(database: Path, *, version: str, now: datetime) -> DatabaseCopy:
    """Copy the database before an update replaces the version, kept apart from the dailies."""
    stamp = now.astimezone().strftime(TAKEN_AT_STAMP)
    target = backups_folder(database) / PRE_UPDATE_FOLDER_NAME / f"history-{stamp}-{version}.db"
    return backup_database(database, target)


@dataclass(frozen=True)
class KeptBackup:
    """A backup file kept beside the database: when it was taken and its size."""

    path: Path
    taken_at: datetime
    size: int


@dataclass(frozen=True)
class KeptBackups:
    """The backups kept beside a database, oldest first: the dailies by day, and the pre-update."""

    folder: Path
    daily: list[tuple[date, KeptBackup]]
    pre_update: list[KeptBackup]


def kept_backups(database: Path) -> KeptBackups:
    """The daily and pre-update backups kept beside a database, read from the files alone."""
    pre_update_folder = backups_folder(database) / PRE_UPDATE_FOLDER_NAME
    pre_update = [_kept(path) for path in pre_update_folder.glob("history-*.db") if path.is_file()]
    return KeptBackups(
        backups_folder(database),
        [(day, _kept(path)) for day, path in daily_backups(database)],
        sorted(pre_update, key=lambda kept: kept.taken_at),
    )


def _kept(path: Path) -> KeptBackup:
    found = path.stat()
    return KeptBackup(path, datetime.fromtimestamp(found.st_mtime, UTC), found.st_size)


def daily_backups(database: Path) -> list[tuple[date, Path]]:
    """The daily backups kept beside a database, oldest first."""
    folder = _daily_folder(database)
    if not folder.is_dir():
        return []
    found: list[tuple[date, Path]] = []
    for path in folder.iterdir():
        matched = DAILY_NAME.match(path.name)
        if matched is None or not path.is_file():
            continue
        try:
            found.append((date.fromisoformat(matched.group(1)), path))
        except ValueError:
            continue
    return sorted(found)


def _drop_oldest(database: Path) -> tuple[Path, ...]:
    days = daily_backups(database)
    removed = tuple(path for _, path in days[: max(0, len(days) - DAILY_KEPT)])
    for path in removed:
        path.unlink()
    return removed


class RestoreFailed(Exception):
    """Restore stopped; the message says why and what state it left behind."""


class BackendRestart(Enum):
    RESTARTED = "restarted"
    NOT_LOADED = "not loaded"
    NOT_MANAGED = "not managed"


@dataclass(frozen=True)
class Restored:
    """The backup put in place, where the database it replaced was set aside, and the backend."""

    source: Path
    aside: Path
    copy: DatabaseCopy
    backend: BackendRestart


def find_daily_backup(database: Path, day: date) -> Path:
    """The daily backup of a day, or RestoreFailed naming the days that are kept."""
    days = daily_backups(database)
    for kept, path in days:
        if kept == day:
            return path
    listed = ", ".join(kept.isoformat() for kept, _ in days) or "none"
    raise RestoreFailed(
        f"no daily backup of {day.isoformat()}; the kept ones are {listed} ({NOTHING_CHANGED})"
    )


def restore_backup(
    host: Host,
    layout: Layout,
    database: Path,
    source: Path,
    *,
    profile: Profile,
    now: datetime,
    sleep: Callable[[float], None] = time.sleep,
) -> Restored:
    """Put a backup in the database's place, setting the current database aside, never deleting it.

    Stable stops its backend first and starts it again after; dev leaves launchd alone.
    """
    aside = (
        backups_folder(database)
        / SET_ASIDE_FOLDER_NAME
        / f"history-{now.astimezone().strftime(TAKEN_AT_STAMP)}.db"
    )
    if profile is Profile.DEV:
        try:
            copy = restore_database(source, database, aside)
        except RESTORE_FAILURES as exc:
            raise RestoreFailed(f"{exc} ({NOTHING_CHANGED})") from exc
        return Restored(source, aside, copy, BackendRestart.NOT_MANAGED)
    plist = BACKEND.plist(layout)
    try:
        running = host.job(BACKEND.label).loaded
        if running:
            stop_agent(host, BACKEND.label, sleep=sleep)
    except HostError as exc:
        raise RestoreFailed(f"could not stop the backend: {exc} ({NOTHING_CHANGED})") from exc
    try:
        copy = restore_database(source, database, aside)
    except RESTORE_FAILURES as exc:
        if not running:
            raise RestoreFailed(f"{exc} ({NOTHING_CHANGED})") from exc
        raise RestoreFailed(f"{exc} ({NOTHING_CHANGED}; {_start(host, plist, sleep)})") from exc
    if not running:
        return Restored(source, aside, copy, BackendRestart.NOT_LOADED)
    try:
        start_agent(host, plist, sleep=sleep)
    except HostError as exc:
        raise RestoreFailed(
            f"restored {source} and set the database aside as {aside}, but could not start the"
            f" backend again: {exc}; run install to start it"
        ) from exc
    return Restored(source, aside, copy, BackendRestart.RESTARTED)


def _start(host: Host, plist: Path, sleep: Callable[[float], None]) -> str:
    try:
        start_agent(host, plist, sleep=sleep)
    except HostError as exc:
        return f"the backend could not be started again: {exc}; run install to start it"
    return "the backend was started again"
