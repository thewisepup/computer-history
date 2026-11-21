from __future__ import annotations

import shutil
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Protocol

from computer_history.host import Host, HostError
from computer_history.stable.backups import (
    BackupFailed,
    RestoreFailed,
    restore_backup,
    take_pre_update_backup,
)
from computer_history.stable.gate import GateVerdict, newest_passing, none_passed
from computer_history.stable.launch_agents import BACKEND, load_agent, start_agent, stop_agent
from computer_history.stable.layout import Layout
from computer_history.stable.update_log import UpdateAction, UpdateLogEntry, append_update_log
from computer_history.stable.versions import (
    InstalledVersion,
    build_version,
    point,
    pointed,
    version_name,
)
from computer_history.store import (
    DATABASE_NAME,
    DatabaseCopy,
    spool_hold_path,
    stored_schema_version,
)

FIRST_CYCLE_WAIT_SECONDS = 300.0
FIRST_CYCLE_POLL_SECONDS = 1.0
NOTIFICATION_TITLE = "Computer History update fell back"
NOTHING_CHANGED = "nothing was changed"
BACKEND_LOG_HINT = "see the backend's log"


class UpdateFailed(Exception):
    """Update stopped before switching versions; the message says why and that nothing changed."""


class RollbackFailed(Exception):
    """Rollback stopped; the message says why and what state it left behind."""


class BackendCycle(Protocol):
    """The backend's last completed ingest cycle, as its heartbeat records it."""

    @property
    def cycle_at(self) -> datetime: ...

    @property
    def ok(self) -> bool: ...

    @property
    def error(self) -> str | None: ...


LastCycle = Callable[[], BackendCycle | None]


class UpdateOutcome(Enum):
    UP_TO_DATE = "up to date"
    UPDATED = "updated"
    FELL_BACK = "fell back"


@dataclass(frozen=True)
class UpdateReport:
    """What update did: the version it found, the one it kept, the backup, and any fallback.

    Problems lists what went wrong without stopping it, such as a notification that failed.
    """

    outcome: UpdateOutcome
    commit: str
    kept: str
    skipped: tuple[GateVerdict, ...] = ()
    backup: DatabaseCopy | None = None
    reason: str | None = None
    restored: Path | None = None
    removed: Path | None = None
    problems: tuple[str, ...] = ()

    @property
    def version(self) -> str:
        return version_name(self.commit)


@dataclass(frozen=True)
class RollbackReport:
    """The version rollback left current and the one it kept as previous."""

    current: str
    previous: str
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Switch:
    """An update between switching versions and its first cycle: what to put back on a fallback."""

    old: InstalledVersion
    old_previous: InstalledVersion | None
    new: str
    built: bool
    backup: DatabaseCopy | None


def update(
    host: Host,
    layout: Layout,
    *,
    last_cycle: LastCycle,
    now: Callable[[], datetime],
    sleep: Callable[[float], None] = time.sleep,
) -> UpdateReport:
    """Move current to the newest main commit the release gate passes, falling back on its own.

    The backend restarts on the new version with spool deletion held, and a crash, a failed
    first cycle or none in time puts the old version back.
    """
    old = pointed(layout.current)
    if old is None:
        raise UpdateFailed(f"there is no stable install in {layout.live}; run install first")
    try:
        search = newest_passing(host)
    except HostError as exc:
        raise UpdateFailed(f"{exc} ({NOTHING_CHANGED})") from exc
    if search.chosen is None:
        raise UpdateFailed(f"{none_passed(search.skipped)} ({NOTHING_CHANGED})")
    commit = search.chosen.commit
    if version_name(commit) == old.name:
        return UpdateReport(UpdateOutcome.UP_TO_DATE, commit, old.name, search.skipped)
    switch = _prepare(host, layout, commit, old, now=now, sleep=sleep)
    problem = _switch(host, layout, switch, last_cycle, now=now, sleep=sleep)
    if problem is not None:
        return _fall_back(
            host, layout, switch, problem, commit, search.skipped, now=now, sleep=sleep
        )
    spool_hold_path(_database(layout)).unlink(missing_ok=True)
    problems: list[str] = []
    removed = _remove_version(layout, switch.old_previous, keep=(switch.new, old.name))
    _log(layout, UpdateLogEntry(now(), UpdateAction.UPDATED, old.name, switch.new), problems)
    return UpdateReport(
        UpdateOutcome.UPDATED,
        commit,
        old.name,
        search.skipped,
        switch.backup,
        removed=removed,
        problems=tuple(problems),
    )


def _prepare(
    host: Host,
    layout: Layout,
    commit: str,
    old: InstalledVersion,
    *,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> _Switch:
    """Build the new version, stop the backend and back up the database; undone on any failure."""
    name = version_name(commit)
    try:
        built = build_version(host, layout, commit)
    except (HostError, OSError) as exc:
        raise UpdateFailed(f"could not build version {name}: {exc} ({NOTHING_CHANGED})") from exc
    database = _database(layout)
    stopped = False
    try:
        if host.job(BACKEND.label).loaded:
            stopped = True
            stop_agent(host, BACKEND.label, sleep=sleep)
        backup = None
        if database.is_file():
            backup = take_pre_update_backup(database, version=old.name, now=now())
        spool_hold_path(database).write_text("")
    except (HostError, BackupFailed, OSError) as exc:
        if built:
            shutil.rmtree(layout.versions / name, ignore_errors=True)
        unchanged = NOTHING_CHANGED
        if stopped:
            try:
                start_agent(host, BACKEND.plist(layout), sleep=sleep)
            except HostError as start_error:
                unchanged += f", but the backend could not be started again ({start_error})"
        raise UpdateFailed(f"{exc} ({unchanged})") from exc
    return _Switch(old, pointed(layout.previous), name, built, backup)


def _switch(
    host: Host,
    layout: Layout,
    switch: _Switch,
    last_cycle: LastCycle,
    *,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> str | None:
    """Point current at the new version and start the backend; returns why it failed, if it did."""
    try:
        point(layout.previous, switch.old.name)
        point(layout.current, switch.new)
        started_at = now()
        load_agent(host, layout, BACKEND, sleep=sleep)
    except (HostError, OSError) as exc:
        return f"the backend could not be started on it: {exc}"
    return _first_cycle(host, last_cycle, started_at, sleep)


def _first_cycle(
    host: Host, last_cycle: LastCycle, started_at: datetime, sleep: Callable[[float], None]
) -> str | None:
    """Wait for the backend's first cycle since it started; returns why it failed, if it did."""
    seen_pid = None
    for _ in range(max(1, round(FIRST_CYCLE_WAIT_SECONDS / FIRST_CYCLE_POLL_SECONDS))):
        try:
            cycle = last_cycle()
        except (OSError, ValueError):
            cycle = None
        if cycle is not None and cycle.cycle_at >= started_at:
            if cycle.ok:
                return None
            return f"its first ingest cycle failed: {cycle.error or BACKEND_LOG_HINT}"
        try:
            job = host.job(BACKEND.label)
        except HostError as exc:
            return f"launchd could not be asked about the backend: {exc}"
        if not job.loaded:
            return "the backend is no longer loaded"
        if seen_pid is not None and job.pid != seen_pid:
            return "the backend crashed before its first ingest cycle completed"
        seen_pid = job.pid
        sleep(FIRST_CYCLE_POLL_SECONDS)
    return f"no ingest cycle completed within {FIRST_CYCLE_WAIT_SECONDS:g}s"


def _fall_back(
    host: Host,
    layout: Layout,
    switch: _Switch,
    reason: str,
    commit: str,
    skipped: tuple[GateVerdict, ...],
    *,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> UpdateReport:
    """Put the old version back, restoring the backup when the schema changed, and say so."""
    problems: list[str] = []
    database = _database(layout)
    try:
        if host.job(BACKEND.label).loaded:
            stop_agent(host, BACKEND.label, sleep=sleep)
    except HostError as exc:
        problems.append(f"the new version's backend could not be stopped: {exc}")
    try:
        point(layout.current, switch.old.name)
        if switch.old_previous is None:
            layout.previous.unlink(missing_ok=True)
        else:
            point(layout.previous, switch.old_previous.name)
    except OSError as exc:
        problems.append(f"the pointers could not be put back: {exc}")
    spool_hold_path(database).unlink(missing_ok=True)
    restored = None
    if switch.backup is not None and _schema_changed(database, switch.backup.schema):
        try:
            restored = restore_backup(
                host, layout, database, switch.backup.target, now=now(), sleep=sleep
            ).source
        except RestoreFailed as exc:
            problems.append(f"the pre-update backup could not be restored: {exc}")
    try:
        load_agent(host, layout, BACKEND, sleep=sleep)
    except (HostError, OSError) as exc:
        problems.append(f"the backend could not be started again: {exc} (run install)")
    if switch.built:
        shutil.rmtree(layout.versions / switch.new, ignore_errors=True)
    entry = UpdateLogEntry(now(), UpdateAction.FELL_BACK, switch.new, switch.old.name, reason)
    _log(layout, entry, problems)
    try:
        host.notify(
            NOTIFICATION_TITLE,
            f"Version {switch.new} {reason}; back on {switch.old.name}.",
        )
    except HostError as exc:
        problems.append(f"the notification could not be posted: {exc}")
    return UpdateReport(
        UpdateOutcome.FELL_BACK,
        commit,
        switch.old.name,
        skipped,
        switch.backup,
        reason,
        restored,
        problems=tuple(problems),
    )


def rollback(
    host: Host,
    layout: Layout,
    *,
    now: Callable[[], datetime],
    sleep: Callable[[float], None] = time.sleep,
) -> RollbackReport:
    """Point current at the previous version, keeping the current one as previous, and restart."""
    current = pointed(layout.current)
    if current is None:
        raise RollbackFailed(f"there is no stable install in {layout.live}; run install first")
    previous = pointed(layout.previous)
    if previous is None:
        raise RollbackFailed(f"there is no previous version to roll back to ({NOTHING_CHANGED})")
    try:
        point(layout.previous, current.name)
        point(layout.current, previous.name)
    except OSError as exc:
        raise RollbackFailed(f"could not switch versions: {exc}") from exc
    try:
        load_agent(host, layout, BACKEND, sleep=sleep)
    except (HostError, OSError) as exc:
        raise RollbackFailed(
            f"switched to version {previous.name}, but the backend could not be restarted on it:"
            f" {exc} (run install)"
        ) from exc
    problems: list[str] = []
    entry = UpdateLogEntry(now(), UpdateAction.ROLLED_BACK, current.name, previous.name)
    _log(layout, entry, problems)
    return RollbackReport(previous.name, current.name, tuple(problems))


def _database(layout: Layout) -> Path:
    return layout.live / DATABASE_NAME


def _schema_changed(database: Path, before: int) -> bool:
    try:
        return stored_schema_version(database) != before
    except (OSError, sqlite3.Error):
        return True


def _remove_version(
    layout: Layout, version: InstalledVersion | None, *, keep: tuple[str, ...]
) -> Path | None:
    if version is None or version.name in keep:
        return None
    folder = layout.versions / version.name
    shutil.rmtree(folder, ignore_errors=True)
    return folder


def _log(layout: Layout, entry: UpdateLogEntry, problems: list[str]) -> None:
    try:
        append_update_log(layout.update_log, entry)
    except OSError as exc:
        problems.append(f"the update log could not be written: {exc}")
