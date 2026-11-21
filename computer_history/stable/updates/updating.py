from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from computer_history.host import Host, HostError
from computer_history.stable.gate import GateVerdict, newest_passing, none_passed
from computer_history.stable.launch_agents import BACKEND, load_agent
from computer_history.stable.layout import Layout
from computer_history.stable.update_log import UpdateAction, UpdateLogEntry, append_or_note
from computer_history.stable.updates.falling_back import fall_back
from computer_history.stable.updates.preparing import (
    NOTHING_CHANGED,
    Prepared,
    UpdateFailed,
    prepare,
)
from computer_history.stable.updates.waiting import (
    FIRST_CYCLE_WAIT_SECONDS,
    FirstCycle,
    LastCycle,
    wait_for_first_cycle,
)
from computer_history.stable.versions import InstalledVersion, point, pointed, version_name
from computer_history.store import DatabaseCopy


@dataclass(frozen=True)
class UpdateReport:
    """What update did (no action when already up to date), its versions, backup and problems."""

    action: UpdateAction | None
    commit: str
    kept: str
    skipped: tuple[GateVerdict, ...] = ()
    behind: bool = False
    backup: DatabaseCopy | None = None
    reason: str | None = None
    restored: Path | None = None
    removed: Path | None = None
    interrupted: bool = False
    problems: tuple[str, ...] = ()

    @property
    def version(self) -> str:
        return version_name(self.commit)


def update(
    host: Host,
    layout: Layout,
    *,
    last_cycle: LastCycle,
    now: Callable[[], datetime],
    wait_seconds: float = FIRST_CYCLE_WAIT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> UpdateReport:
    """Move current to the newest main commit the release gate passes, falling back on its own.

    The backend restarts on it with spool deletion held; a crash, a failed cycle or none in time
    puts the old version back.
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
    behind = any(version_name(verdict.commit) == old.name for verdict in search.skipped)
    if behind or version_name(commit) == old.name:
        return UpdateReport(None, commit, old.name, search.skipped, behind=behind)
    prepared = prepare(host, layout, commit, old, now=now, sleep=sleep)
    first = _switch(
        host, layout, prepared, last_cycle, now=now, wait_seconds=wait_seconds, sleep=sleep
    )
    if first.problem is not None:
        fell_back = fall_back(host, layout, prepared, first.problem, now=now, sleep=sleep)
        return UpdateReport(
            UpdateAction.FELL_BACK,
            commit,
            old.name,
            search.skipped,
            backup=prepared.backup,
            reason=first.problem,
            restored=fell_back.restored,
            interrupted=first.interrupted,
            problems=fell_back.problems,
        )
    problems: list[str] = []
    try:
        prepared.hold.release()
    except OSError as exc:
        problems.append(f"the spool hold {prepared.hold.path} could not be removed: {exc}")
    removed = _remove_version(layout, prepared.old_previous, keep=(prepared.new, old.name))
    entry = UpdateLogEntry(now(), UpdateAction.UPDATED, old.name, prepared.new)
    append_or_note(layout.update_log, entry, problems)
    return UpdateReport(
        UpdateAction.UPDATED,
        commit,
        old.name,
        search.skipped,
        backup=prepared.backup,
        removed=removed,
        problems=tuple(problems),
    )


def _switch(
    host: Host,
    layout: Layout,
    prepared: Prepared,
    last_cycle: LastCycle,
    *,
    now: Callable[[], datetime],
    wait_seconds: float,
    sleep: Callable[[float], None],
) -> FirstCycle:
    try:
        point(layout.previous, prepared.old.name)
        point(layout.current, prepared.new)
        started_at = now()
        load_agent(host, layout, BACKEND, sleep=sleep)
    except (HostError, OSError) as exc:
        return FirstCycle(f"the backend could not be started on the new version: {exc}")
    return wait_for_first_cycle(host, last_cycle, started_at, wait_seconds=wait_seconds)


def _remove_version(
    layout: Layout, version: InstalledVersion | None, *, keep: tuple[str, ...]
) -> Path | None:
    if version is None or version.name in keep:
        return None
    folder = layout.versions / version.name
    shutil.rmtree(folder, ignore_errors=True)
    return folder
