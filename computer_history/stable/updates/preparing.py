from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from computer_history.host import Host, HostError
from computer_history.stable.backups import BackupFailed, take_pre_update_backup
from computer_history.stable.launch_agents import BACKEND, start_agent, stop_agent
from computer_history.stable.layout import NOTHING_CHANGED, Layout
from computer_history.stable.versions import InstalledVersion, build_version, pointed, version_name
from computer_history.store import DatabaseCopy, SpoolHold, sidecars


class UpdateFailed(Exception):
    """Update stopped before switching versions; the message says why and what it left."""


@dataclass(frozen=True)
class Prepared:
    """What update readied before switching: both versions, the backup and the spool hold."""

    old: InstalledVersion
    old_previous: InstalledVersion | None
    new: str
    built: bool
    backup: DatabaseCopy | None
    hold: SpoolHold


def prepare(
    host: Host,
    layout: Layout,
    commit: str,
    old: InstalledVersion,
    *,
    now: Callable[[], datetime],
    sleep: Callable[[float], None] = time.sleep,
) -> Prepared:
    """Build the new version, stop the backend, back up the database and place the spool hold.

    Anything that stops it, Ctrl-C included, undoes what it did first and restarts the backend.
    """
    name = version_name(commit)
    try:
        built = build_version(host, layout, commit)
    except (HostError, OSError) as exc:
        raise UpdateFailed(f"could not build version {name}: {exc} ({NOTHING_CHANGED})") from exc
    hold = SpoolHold.beside(layout.database)
    was_loaded = False
    backup = None
    try:
        was_loaded = host.job(BACKEND.label).loaded
        if was_loaded:
            stop_agent(host, BACKEND.label, sleep=sleep)
        if layout.database.is_file():
            backup = take_pre_update_backup(layout.database, version=old.name, now=now())
        hold.place()
    except BaseException as exc:
        restart = was_loaded and not _still_loaded(host)
        left = _undo(host, layout, name if built else None, backup, restart, sleep)
        if isinstance(exc, HostError | BackupFailed | OSError):
            raise UpdateFailed(f"{exc} ({left})") from exc
        exc.add_note(left)
        raise
    return Prepared(old, pointed(layout.previous), name, built, backup, hold)


def _undo(
    host: Host,
    layout: Layout,
    built: str | None,
    backup: DatabaseCopy | None,
    restart: bool,
    sleep: Callable[[float], None],
) -> str:
    kept: list[str] = []
    if backup is not None:
        try:
            for path in (backup.target, *sidecars(backup.target)):
                path.unlink(missing_ok=True)
        except OSError as exc:
            kept.append(f"the pre-update backup {backup.target} could not be removed ({exc})")
    if built is not None:
        shutil.rmtree(layout.versions / built, ignore_errors=True)
    if restart:
        try:
            start_agent(host, BACKEND.plist(layout), sleep=sleep)
        except HostError as exc:
            kept.append(f"the backend could not be started again ({exc}; run install)")
    if not kept:
        return NOTHING_CHANGED
    return f"{NOTHING_CHANGED} to the install, but {'; '.join(kept)}"


def _still_loaded(host: Host) -> bool:
    try:
        return host.job(BACKEND.label).loaded
    except HostError:
        return True
