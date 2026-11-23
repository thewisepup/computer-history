from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from computer_history.host import Host, HostError
from computer_history.stable.backups import pre_update_backup_of
from computer_history.stable.capture_agent import installed_agent
from computer_history.stable.launch_agents import BACKEND, load_agent
from computer_history.stable.layout import NOTHING_CHANGED, Layout
from computer_history.stable.update_log import UpdateAction, UpdateLogEntry, append_or_note
from computer_history.stable.versions import point, pointed, supported_schema
from computer_history.store import stored_schema_version


class RollbackFailed(Exception):
    """Rollback stopped; the message says why and what it left."""


@dataclass(frozen=True)
class RollbackReport:
    """The version rollback made current, the one it kept as previous, the commit the capture agent
    it left in place was built from (None when unknown), and what went wrong."""

    current: str
    previous: str
    agent: str | None
    problems: tuple[str, ...] = ()


def rollback(
    host: Host,
    layout: Layout,
    *,
    now: Callable[[], datetime],
    sleep: Callable[[float], None] = time.sleep,
) -> RollbackReport:
    """Point current at the previous version, keep the current one as previous, and restart the
    backend; the capture agent stays as it is."""
    current = pointed(layout.current)
    if current is None:
        raise RollbackFailed(f"there is no stable install in {layout.live}; run install first")
    previous = pointed(layout.previous)
    if previous is None:
        raise RollbackFailed(f"there is no previous version to roll back to ({NOTHING_CHANGED})")
    problems: list[str] = []
    _check_schema(layout, previous.name, problems)
    try:
        point(layout.current, previous.name)
    except OSError as exc:
        raise RollbackFailed(
            f"could not point current at {previous.name}: {exc} ({NOTHING_CHANGED})"
        ) from exc
    try:
        point(layout.previous, current.name)
    except OSError as exc:
        raise RollbackFailed(
            f"could not point previous at {current.name}: {exc} ({_undone(layout, current.name)})"
        ) from exc
    try:
        load_agent(host, layout, BACKEND, sleep=sleep)
    except (HostError, OSError) as exc:
        raise RollbackFailed(
            f"switched to version {previous.name}, but the backend could not be restarted on it:"
            f" {exc} (run install)"
        ) from exc
    entry = UpdateLogEntry(now(), UpdateAction.ROLLED_BACK, current.name, previous.name)
    append_or_note(layout.update_log, entry, problems)
    agent = installed_agent(layout)
    built_from = None if agent is None else agent.built_from
    return RollbackReport(previous.name, current.name, built_from, tuple(problems))


def _check_schema(layout: Layout, target: str, problems: list[str]) -> None:
    supported = supported_schema(layout, target)
    if supported is None:
        problems.append(f"could not tell which schema version {target} opens; check status")
        return
    try:
        stored = stored_schema_version(layout.database) if layout.database.is_file() else 0
    except (OSError, sqlite3.Error) as exc:
        problems.append(f"could not read the database's schema version: {exc}")
        return
    if stored <= supported:
        return
    backup = pre_update_backup_of(layout.database, target)
    put_back = (
        "put a backup from before the update back first with `computer-history restore`"
        if backup is None
        else f"put its pre-update backup back first with `computer-history restore {backup}`"
    )
    raise RollbackFailed(
        f"the database is at schema v{stored}, newer than version {target} can open"
        f" (v{supported}); {put_back}, then roll back ({NOTHING_CHANGED})"
    )


def _undone(layout: Layout, name: str) -> str:
    try:
        point(layout.current, name)
    except OSError as exc:
        return (
            f"current still names the previous version and {name} is no longer pointed at, but"
            f" its folder is kept; pointing current back failed too: {exc}"
        )
    return f"current points at {name} again; {NOTHING_CHANGED}"
