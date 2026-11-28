from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path

from computer_history.host import AgentNotUnregistered, Host, HostError
from computer_history.stable.capture_agent import (
    installed_agent,
    keep_installed_app,
    record_installed_agent_or_note,
    set_aside_fallen_back,
)
from computer_history.stable.layout import Layout
from computer_history.stable.update_log import UpdateAction, UpdateLogEntry, append_or_note
from computer_history.stable.updates.preparing import Prepared
from computer_history.stable.versions import carried_agent

REINSTALL_HINT = "run capture-agent/scripts/install.sh from a checkout at main"


class SwapEnd(Enum):
    LEFT_RUNNING = auto()
    FAILED = auto()
    STARTED = auto()


@dataclass(frozen=True)
class AgentSwap:
    """How the swap ended: the installed agent left running untouched, a new app that failed and
    why, or one started and when it was registered."""

    end: SwapEnd
    at: datetime | None = None
    failure: str | None = None
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentFellBack:
    """Where an agent fallback kept the build that fell back, and each step that went wrong."""

    kept: Path | None
    problems: tuple[str, ...]


def swap_agent(host: Host, layout: Layout, prepared: Prepared) -> AgentSwap:
    """Keep the installed app in the old version's folder, then install the new version's app
    over the fixed path and record it."""
    old = layout.versions / prepared.old.name
    try:
        keep_installed_app(layout, old)
    except OSError as exc:
        kept = f"the installed capture agent could not be kept in {prepared.old.name}: {exc}"
        return AgentSwap(SwapEnd.LEFT_RUNNING, problems=(kept,))
    installed = installed_agent(layout)
    try:
        layout.installed_agent.unlink(missing_ok=True)
        at = host.install_agent(
            layout.agent_app(layout.versions / prepared.new), layout.capture_agent_app
        )
    except AgentNotUnregistered as exc:
        problems = [
            f"the installed capture agent could not be unregistered, so it keeps running: {exc}"
        ]
        if installed is not None:
            record_installed_agent_or_note(
                layout, installed.built_from, installed.installed_at, problems
            )
        return AgentSwap(SwapEnd.LEFT_RUNNING, problems=tuple(problems))
    except (HostError, OSError) as exc:
        failure = f"the new capture agent could not be started: {exc}"
        return AgentSwap(SwapEnd.FAILED, failure=failure)
    problems: list[str] = []
    record_installed_agent_or_note(layout, prepared.agent.built_from, at, problems)
    return AgentSwap(SwapEnd.STARTED, at, problems=tuple(problems))


def fall_back_agent(
    host: Host,
    layout: Layout,
    prepared: Prepared,
    reason: str,
    *,
    now: Callable[[], datetime],
) -> AgentFellBack:
    """Put the old version's agent app back over the fixed path and record it, keep the build that
    fell back aside in the new version's folder, log and notify, each step running whatever the
    one before it did."""
    old, new = prepared.old.name, prepared.new
    problems: list[str] = []
    kept = None
    if _reinstall(host, layout, old, problems):
        kept = _set_aside(layout, prepared, problems)
    entry = UpdateLogEntry(now(), UpdateAction.AGENT_FELL_BACK, new, old, reason)
    append_or_note(layout.update_log, entry, problems)
    notice = f"The capture agent from {new} fell back to {old}'s: {reason}."
    if kept is not None:
        notice += f" Its build is kept at {kept}."
    try:
        host.notify(notice)
    except HostError as exc:
        problems.append(f"the notification could not be posted: {exc}")
    return AgentFellBack(kept, tuple(problems))


def _reinstall(host: Host, layout: Layout, old: str, problems: list[str]) -> bool:
    folder = layout.versions / old
    app = layout.agent_app(folder)
    try:
        layout.installed_agent.unlink(missing_ok=True)
    except OSError as exc:
        problems.append(f"the installed agent's record could not be removed: {exc}")
    if not app.is_dir():
        problems.append(
            f"{old} holds no capture agent to put back, so the new one stays ({REINSTALL_HINT})"
        )
        return False
    try:
        at = host.install_agent(app, layout.capture_agent_app)
    except AgentNotUnregistered as exc:
        stays = f"the new capture agent could not be unregistered, so it stays: {exc}"
        problems.append(f"{stays} ({REINSTALL_HINT})")
        return False
    except (HostError, OSError) as exc:
        problems.append(f"{old}'s capture agent could not be put back: {exc} ({REINSTALL_HINT})")
        return False
    built_from = carried_agent(layout, folder)
    if built_from is not None:
        record_installed_agent_or_note(layout, built_from, at, problems)
    return True


def _set_aside(layout: Layout, prepared: Prepared, problems: list[str]) -> Path | None:
    folder = layout.versions / prepared.new
    try:
        return set_aside_fallen_back(layout, folder, layout.versions / prepared.old.name)
    except OSError as exc:
        problems.append(f"the build that fell back could not be kept aside in {folder}: {exc}")
        return None
