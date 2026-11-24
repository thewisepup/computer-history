from __future__ import annotations

import shutil
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from computer_history.host import Host, HostError
from computer_history.stable.backups import RestoreFailed, restore_backup
from computer_history.stable.launch_agents import BACKEND
from computer_history.stable.layout import Layout
from computer_history.stable.stopped_agents import AgentNotStopped
from computer_history.stable.update_log import UpdateAction, UpdateLogEntry, append_or_note
from computer_history.stable.updates.phases import UpdatePhase
from computer_history.stable.updates.preparing import Prepared
from computer_history.stable.versions import point
from computer_history.store import stored_schema_version


@dataclass(frozen=True)
class FellBack:
    """What a fallback did: the backup it restored, and each step that went wrong."""

    restored: Path | None
    problems: tuple[str, ...]


def fall_back(
    host: Host,
    layout: Layout,
    prepared: Prepared,
    reason: str,
    *,
    now: Callable[[], datetime],
    sleep: Callable[[float], None] = time.sleep,
) -> FellBack:
    """Put the old version back, restoring the backup only when the schema changed, and notify.

    The spool hold is released only once the new backend is confirmed stopped and the restore done.
    """
    prepared.progress.advance(UpdatePhase.FALLING_BACK)
    problems: list[str] = []
    old, new = prepared.old.name, prepared.new
    stopped = _stop_new_backend(prepared, problems)
    pointed_back = _point_back(layout, prepared, problems)
    restored = _restore_if_migrated(host, layout, prepared, problems, now, sleep)
    if stopped:
        _release_hold(prepared, problems)
    else:
        problems.append(
            f"kept the spool hold {prepared.hold.path}, since the new backend may still run; the"
            " backend's next ok cycle removes it"
        )
    try:
        prepared.stopped.load(BACKEND)
    except (HostError, OSError) as exc:
        problems.append(f"the backend could not be started again: {exc} (run install)")
    folder = layout.versions / new
    if prepared.built:
        if stopped and pointed_back:
            shutil.rmtree(folder, ignore_errors=True)
        else:
            problems.append(f"kept {folder}, since its backend or a pointer may still use it")
    entry = UpdateLogEntry(now(), UpdateAction.FELL_BACK, new, old, reason)
    append_or_note(layout.update_log, entry, problems)
    back = f"back on {old}" if pointed_back else "run computer-history status to see where it is"
    try:
        host.notify(f"Update to {new} fell back: {reason}; {back}.")
    except HostError as exc:
        problems.append(f"the notification could not be posted: {exc}")
    prepared.progress.advance(UpdatePhase.FELL_BACK)
    return FellBack(restored, tuple(problems))


def _stop_new_backend(prepared: Prepared, problems: list[str]) -> bool:
    try:
        prepared.stopped.stop((BACKEND,))
    except AgentNotStopped as exc:
        problems.append(f"the new version's backend could not be confirmed stopped: {exc}")
        return False
    return True


def _release_hold(prepared: Prepared, problems: list[str]) -> None:
    try:
        prepared.hold.release()
    except OSError as exc:
        problems.append(
            f"the spool hold {prepared.hold.path} could not be removed ({exc}); ingest keeps"
            " spool files until it is"
        )


def _point_back(layout: Layout, prepared: Prepared, problems: list[str]) -> bool:
    try:
        point(layout.current, prepared.old.name)
    except OSError as exc:
        problems.append(f"current could not be pointed back at {prepared.old.name}: {exc}")
        return False
    try:
        if prepared.old_previous is None:
            layout.previous.unlink(missing_ok=True)
        else:
            point(layout.previous, prepared.old_previous.name)
    except OSError as exc:
        problems.append(f"previous could not be put back: {exc}")
        return False
    return True


def _restore_if_migrated(
    host: Host,
    layout: Layout,
    prepared: Prepared,
    problems: list[str],
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> Path | None:
    backup = prepared.backup
    if backup is None or not _schema_changed(layout.database, backup.schema):
        return None
    try:
        return restore_backup(
            host, layout, layout.database, backup.target, now=now(), sleep=sleep
        ).source
    except RestoreFailed as exc:
        problems.append(f"the pre-update backup could not be restored: {exc}")
        return None


def _schema_changed(database: Path, before: int) -> bool:
    try:
        return stored_schema_version(database) != before
    except (OSError, sqlite3.Error):
        return True
