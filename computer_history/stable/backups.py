from __future__ import annotations

import os
import re
import sqlite3
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path

from computer_history.host import Host, HostError
from computer_history.stable.launch_agents import (
    BACKEND,
    DAILY_BACKUP,
    WATCHDOG,
    LaunchAgent,
    start_agent,
    stop_agent,
)
from computer_history.stable.layout import NOTHING_CHANGED, Layout
from computer_history.store import (
    DatabaseCopy,
    DatabaseExists,
    backup_database,
    existing_database_files,
    restore_database,
    sidecars,
)

BACKUPS_FOLDER_NAME = "backups"
DAILY_FOLDER_NAME = "daily"
PRE_UPDATE_FOLDER_NAME = "pre-update"
SET_ASIDE_FOLDER_NAME = "set-aside"
TAKEN_AT_STAMP = "%Y-%m-%dT%H%M%S"
DAILY_KEPT = 7
DAILY_BACKUP_MAX_AGE_DAYS = 1
DAILY_NAME = re.compile(r"^history-(\d{4}-\d{2}-\d{2})\.db$")
PRE_UPDATE_NAME = re.compile(r"^history-.+\.db$")
SQLITE_HEADER = b"SQLite format 3\x00"
COPY_FAILURES = (OSError, sqlite3.Error, RuntimeError)
STOPPED_FOR_RESTORE = (DAILY_BACKUP, WATCHDOG, BACKEND)


class BackupFailed(Exception):
    """A backup was not taken; the message says why."""


class RestoreFailed(Exception):
    """Restore stopped; the message says why and what state it left behind."""


def backups_folder(database: Path) -> Path:
    """Where a database's backups are kept: a folder beside it."""
    return database.parent / BACKUPS_FOLDER_NAME


def daily_backup_path(database: Path, day: date) -> Path:
    return _daily_folder(database) / f"history-{day.isoformat()}.db"


def _daily_folder(database: Path) -> Path:
    return backups_folder(database) / DAILY_FOLDER_NAME


class DailyOutcome(Enum):
    TAKEN = "taken"
    ALREADY_TAKEN = "already taken"
    NO_DATABASE = "no database"


@dataclass(frozen=True)
class DailyBackup:
    """What a daily backup run did, the day's file, the copy it took and the days it removed."""

    outcome: DailyOutcome
    path: Path
    copy: DatabaseCopy | None
    removed: tuple[Path, ...]


def take_daily_backup(database: Path, today: date) -> DailyBackup:
    """Take today's backup unless it is taken, then remove the days past the newest seven."""
    target = daily_backup_path(database, today)
    if not database.is_file():
        return DailyBackup(DailyOutcome.NO_DATABASE, target, None, ())
    copy = None
    try:
        if not _complete(target):
            for path in existing_database_files(target):
                path.unlink()
            try:
                copy = backup_database(database, target)
            except DatabaseExists:
                if not _complete(target):
                    raise
        removed = _drop_oldest(database)
    except COPY_FAILURES as exc:
        raise BackupFailed(str(exc)) from exc
    outcome = DailyOutcome.ALREADY_TAKEN if copy is None else DailyOutcome.TAKEN
    return DailyBackup(outcome, target, copy, removed)


def take_pre_update_backup(database: Path, *, version: str, now: datetime) -> DatabaseCopy:
    """Copy the database before an update replaces the version, kept apart from the dailies."""
    stamp = now.astimezone().strftime(TAKEN_AT_STAMP)
    target = backups_folder(database) / PRE_UPDATE_FOLDER_NAME / f"history-{stamp}-{version}.db"
    try:
        return backup_database(database, target)
    except COPY_FAILURES as exc:
        raise BackupFailed(str(exc)) from exc


def _complete(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            return file.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError:
        return False


def _drop_oldest(database: Path) -> tuple[Path, ...]:
    days = daily_backups(database)
    removed = tuple(kept.path for kept in days[: max(0, len(days) - DAILY_KEPT)])
    for path in removed:
        for file in (path, *sidecars(path)):
            file.unlink(missing_ok=True)
    return removed


@dataclass(frozen=True)
class KeptBackup:
    """A backup file beside the database: its day (a daily's only), when it was taken, its size."""

    path: Path
    day: date | None
    taken_at: datetime
    size: int


@dataclass(frozen=True)
class BackupInventory:
    """The backups kept beside a database, oldest first: the dailies and the pre-update ones."""

    folder: Path
    daily: list[KeptBackup]
    pre_update: list[KeptBackup]

    def overdue(self, today: date) -> bool:
        """Whether there is no daily backup, or the newest is older than yesterday."""
        newest = self.daily[-1].day if self.daily else None
        return newest is None or (today - newest).days > DAILY_BACKUP_MAX_AGE_DAYS


def backup_inventory(database: Path) -> BackupInventory:
    """The daily and pre-update backups beside a database, read from the files alone."""
    pre_update = [
        _kept(path, found, None)
        for path, found in _files(backups_folder(database) / PRE_UPDATE_FOLDER_NAME)
        if PRE_UPDATE_NAME.match(path.name)
    ]
    return BackupInventory(
        backups_folder(database),
        daily_backups(database),
        sorted(pre_update, key=lambda kept: kept.taken_at),
    )


def daily_backups(database: Path) -> list[KeptBackup]:
    """The daily backups kept beside a database, oldest first."""
    found: list[KeptBackup] = []
    for path, stat_result in _files(_daily_folder(database)):
        matched = DAILY_NAME.match(path.name)
        if matched is None:
            continue
        try:
            day = date.fromisoformat(matched.group(1))
        except ValueError:
            continue
        found.append(_kept(path, stat_result, day))
    return sorted(found, key=lambda kept: kept.day or date.min)


def _files(folder: Path) -> list[tuple[Path, os.stat_result]]:
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    found: list[tuple[Path, os.stat_result]] = []
    for name in names:
        try:
            stat_result = (folder / name).stat()
        except OSError:
            continue
        if stat.S_ISREG(stat_result.st_mode):
            found.append((folder / name, stat_result))
    return found


def _kept(path: Path, found: os.stat_result, day: date | None) -> KeptBackup:
    return KeptBackup(path, day, datetime.fromtimestamp(found.st_mtime, UTC), found.st_size)


def find_daily_backup(database: Path, day: date) -> Path:
    """The daily backup of a day, or RestoreFailed naming the days that are kept."""
    days = daily_backups(database)
    for kept in days:
        if kept.day == day:
            return kept.path
    listed = ", ".join(str(kept.day) for kept in days) or "none"
    raise RestoreFailed(
        f"no daily backup of {day.isoformat()}; the kept ones are {listed} ({NOTHING_CHANGED})"
    )


@dataclass(frozen=True)
class Restored:
    """The backup put in place, where the replaced database went, and the agents stopped around it.

    Managed is false when the target is not the live database, so launchd was left alone.
    """

    source: Path
    aside: Path | None
    copy: DatabaseCopy
    managed: bool
    restarted: tuple[LaunchAgent, ...]


def restore_backup(
    host: Host,
    layout: Layout,
    database: Path,
    backup: date | Path,
    *,
    now: datetime,
    sleep: Callable[[float], None] = time.sleep,
) -> Restored:
    """Put a day's daily backup, or a backup file, in the database's place, setting it aside.

    For the live database the backend, the watchdog and the daily backup are stopped first and
    started after.
    """
    source = find_daily_backup(database, backup) if isinstance(backup, date) else backup
    if not source.is_file():
        raise RestoreFailed(f"no backup at {source} ({NOTHING_CHANGED})")
    stamp = now.astimezone().strftime(TAKEN_AT_STAMP)
    aside = backups_folder(database) / SET_ASIDE_FOLDER_NAME / f"history-{stamp}.db"
    managed = _is_live(database, layout)
    stopped = _stop(host, layout, sleep) if managed else ()
    try:
        restored = restore_database(source, database, aside)
    except COPY_FAILURES as exc:
        raise RestoreFailed(f"{exc} ({_unchanged(host, layout, stopped, sleep)})") from exc
    failed = _start_again(host, layout, stopped, sleep)
    if failed:
        raise RestoreFailed(
            f"restored {source}{_aside_note(restored.aside)}, but {failed}; run install to start"
            " them"
        )
    return Restored(source, restored.aside, restored.copy, managed, stopped)


def _is_live(database: Path, layout: Layout) -> bool:
    live = layout.database
    if database.resolve() == live.resolve():
        return True
    return database.exists() and live.exists() and os.path.samefile(database, live)


def _stop(host: Host, layout: Layout, sleep: Callable[[float], None]) -> tuple[LaunchAgent, ...]:
    stopped: list[LaunchAgent] = []
    for agent in STOPPED_FOR_RESTORE:
        try:
            if not host.job(agent.label).loaded:
                continue
            stopped.append(agent)
            stop_agent(host, agent.label, sleep=sleep)
        except HostError as exc:
            unchanged = _unchanged(host, layout, tuple(reversed(stopped)), sleep)
            raise RestoreFailed(f"could not stop {agent.label}: {exc} ({unchanged})") from exc
    return tuple(reversed(stopped))


def _unchanged(
    host: Host, layout: Layout, stopped: tuple[LaunchAgent, ...], sleep: Callable[[float], None]
) -> str:
    failed = _start_again(host, layout, stopped, sleep)
    if failed:
        return f"{NOTHING_CHANGED} to the database, but {failed}; run install to start them"
    if not stopped:
        return NOTHING_CHANGED
    names = [agent.name for agent in stopped]
    started = " and ".join(filter(None, (", ".join(names[:-1]), names[-1])))
    return f"{NOTHING_CHANGED}; {started} started again"


def _start_again(
    host: Host, layout: Layout, stopped: tuple[LaunchAgent, ...], sleep: Callable[[float], None]
) -> str | None:
    failed: list[str] = []
    for agent in stopped:
        try:
            start_agent(host, agent.plist(layout), sleep=sleep)
        except HostError as exc:
            if not _loaded(host, agent.label):
                failed.append(f"{agent.label} could not be started again ({exc})")
    return "; ".join(failed) or None


def _loaded(host: Host, label: str) -> bool:
    try:
        return host.job(label).loaded
    except HostError:
        return False


def _aside_note(aside: Path | None) -> str:
    return "" if aside is None else f" and set the database aside as {aside}"
