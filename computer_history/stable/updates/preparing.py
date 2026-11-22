from __future__ import annotations

import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from computer_history.host import Host, HostError
from computer_history.stable.backups import BackupFailed, take_pre_update_backup
from computer_history.stable.capture_agent import AgentPlan, holds_agent, place_agent, plan_agent
from computer_history.stable.launch_agents import BACKEND
from computer_history.stable.layout import NOTHING_CHANGED, Layout
from computer_history.stable.stopped_agents import StoppedAgents
from computer_history.stable.versions import InstalledVersion, build_version, pointed, version_name
from computer_history.store import DatabaseCopy, SpoolHold, sidecars


class UpdateFailed(Exception):
    """Update stopped before switching versions; the message says why and what it left."""


@dataclass(frozen=True)
class Prepared:
    """What update readied before switching: both versions, the agent, the stopped backend, the
    backup and the hold."""

    old: InstalledVersion
    old_previous: InstalledVersion | None
    new: str
    built: bool
    agent: AgentPlan
    stopped: StoppedAgents
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
    """Build the new version and its agent app, stop the backend, back up and place the spool hold.

    Anything that stops it, Ctrl-C included, undoes what it did first and restarts the backend.
    """
    name = version_name(commit)
    folder = layout.versions / name
    try:
        agent = plan_agent(host, layout, commit, old)
    except HostError as exc:
        raise UpdateFailed(
            f"could not tell whether the capture agent changed: {exc} ({NOTHING_CHANGED})"
        ) from exc
    placing = not holds_agent(layout, folder)
    if agent.changed and placing:
        try:
            host.check_agent_toolchain()
        except HostError as exc:
            raise UpdateFailed(
                f"cannot build the capture agent: {exc} ({NOTHING_CHANGED})"
            ) from exc
    try:
        built = build_version(host, layout, commit)
    except (HostError, OSError) as exc:
        raise UpdateFailed(f"could not build version {name}: {exc} ({NOTHING_CHANGED})") from exc
    if placing:
        _place(host, layout, agent, name, built=built)
    hold = SpoolHold.beside(layout.database)
    stopped = StoppedAgents(host, layout, sleep=sleep)
    backup = None
    try:
        stopped.stop((BACKEND,))
        if layout.database.is_file():
            backup = take_pre_update_backup(layout.database, version=old.name, now=now())
        hold.place()
    except BaseException as exc:
        left = _undo(layout, name if built else None, backup, stopped)
        if isinstance(exc, HostError | BackupFailed | OSError):
            raise UpdateFailed(f"{exc} ({left})") from exc
        exc.add_note(left)
        raise
    return Prepared(old, pointed(layout.previous), name, built, agent, stopped, backup, hold)


def _place(host: Host, layout: Layout, agent: AgentPlan, name: str, *, built: bool) -> None:
    try:
        place_agent(host, layout, agent, layout.versions / name)
    except BaseException as exc:
        if built:
            shutil.rmtree(layout.versions / name, ignore_errors=True)
        if not isinstance(exc, HostError | OSError):
            raise
        doing = "build the capture agent for" if agent.changed else "copy the capture agent into"
        raise UpdateFailed(f"could not {doing} version {name}: {exc} ({NOTHING_CHANGED})") from exc


def _undo(
    layout: Layout, built: str | None, backup: DatabaseCopy | None, stopped: StoppedAgents
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
    for agent, exc in stopped.start_again_unless_loaded().failed:
        kept.append(f"the {agent.name} could not be started again ({exc}; run install)")
    if not kept:
        return NOTHING_CHANGED
    return f"{NOTHING_CHANGED} to the install, but {'; '.join(kept)}"
