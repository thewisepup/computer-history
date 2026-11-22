from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from computer_history.host import Host, HostError
from computer_history.stable.capture_agent import (
    carried_agent,
    keep_installed_app,
    record_installed_agent,
)
from computer_history.stable.layout import Layout
from computer_history.stable.update_log import UpdateAction, UpdateLogEntry, append_or_note
from computer_history.stable.updates.preparing import Prepared

REINSTALL_HINT = "run capture-agent/scripts/install.sh from a checkout at main"


@dataclass(frozen=True)
class AgentSwap:
    """How the swap went: when the new app went in, or why to put the old one back and whether
    the fixed path was touched."""

    at: datetime | None
    failure: str | None = None
    touched: bool = True
    problems: tuple[str, ...] = ()


def swap_agent(
    host: Host, layout: Layout, prepared: Prepared, *, now: Callable[[], datetime]
) -> AgentSwap:
    """Keep the installed app in the old version's folder, then install the new version's app
    over the fixed path and record it."""
    old = layout.versions / prepared.old.name
    try:
        keep_installed_app(layout, old)
    except OSError as exc:
        failure = f"the installed capture agent could not be kept in {prepared.old.name}: {exc}"
        return AgentSwap(None, failure, touched=False)
    try:
        layout.installed_agent.unlink(missing_ok=True)
        host.install_agent(
            layout.agent_app(layout.versions / prepared.new), layout.capture_agent_app
        )
    except (HostError, OSError) as exc:
        return AgentSwap(None, f"the new capture agent could not be started: {exc}")
    at = now()
    try:
        record_installed_agent(layout, prepared.agent.built_from, at)
    except OSError as exc:
        return AgentSwap(
            at, problems=(f"the installed agent's record could not be written: {exc}",)
        )
    return AgentSwap(at)


def fall_back_agent(
    host: Host,
    layout: Layout,
    prepared: Prepared,
    reason: str,
    *,
    reinstall: bool,
    now: Callable[[], datetime],
) -> tuple[str, ...]:
    """Put the old version's agent app back over the fixed path and record it, log and notify,
    each step running whatever the one before it did; returns the steps that went wrong."""
    old, new = prepared.old.name, prepared.new
    problems: list[str] = []
    if reinstall:
        _reinstall(host, layout, old, problems, now)
    entry = UpdateLogEntry(now(), UpdateAction.AGENT_FELL_BACK, new, old, reason)
    append_or_note(layout.update_log, entry, problems)
    try:
        host.notify(f"The capture agent from {new} fell back to {old}'s: {reason}.")
    except HostError as exc:
        problems.append(f"the notification could not be posted: {exc}")
    return tuple(problems)


def _reinstall(
    host: Host, layout: Layout, old: str, problems: list[str], now: Callable[[], datetime]
) -> None:
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
        return
    try:
        host.install_agent(app, layout.capture_agent_app)
    except (HostError, OSError) as exc:
        problems.append(f"{old}'s capture agent could not be put back: {exc} ({REINSTALL_HINT})")
        return
    built_from = carried_agent(layout, folder)
    if built_from is None:
        return
    try:
        record_installed_agent(layout, built_from, now())
    except OSError as exc:
        problems.append(f"the installed agent's record could not be written: {exc}")
