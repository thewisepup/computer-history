from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from computer_history.host import Host, HostError
from computer_history.stable.launch_agents import BACKEND, load_agent
from computer_history.stable.layout import NOTHING_CHANGED, Layout
from computer_history.stable.update_log import UpdateAction, UpdateLogEntry, append_or_note
from computer_history.stable.versions import point, pointed


class RollbackFailed(Exception):
    """Rollback stopped; the message says why and what it left."""


@dataclass(frozen=True)
class RollbackReport:
    """The version rollback made current, the one it kept as previous, and what went wrong."""

    current: str
    previous: str
    problems: tuple[str, ...] = ()


def rollback(
    host: Host,
    layout: Layout,
    *,
    now: Callable[[], datetime],
    sleep: Callable[[float], None] = time.sleep,
) -> RollbackReport:
    """Point current at the previous version, keep the current one as previous, and restart."""
    current = pointed(layout.current)
    if current is None:
        raise RollbackFailed(f"there is no stable install in {layout.live}; run install first")
    previous = pointed(layout.previous)
    if previous is None:
        raise RollbackFailed(f"there is no previous version to roll back to ({NOTHING_CHANGED})")
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
    problems: list[str] = []
    entry = UpdateLogEntry(now(), UpdateAction.ROLLED_BACK, current.name, previous.name)
    append_or_note(layout.update_log, entry, problems)
    return RollbackReport(previous.name, current.name, tuple(problems))


def _undone(layout: Layout, name: str) -> str:
    try:
        point(layout.current, name)
    except OSError as exc:
        return (
            f"current still names the previous version and {name} is no longer pointed at, but"
            f" its folder is kept; pointing current back failed too: {exc}"
        )
    return f"current points at {name} again; {NOTHING_CHANGED}"
