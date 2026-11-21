from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from computer_history.host import Host, HostError
from computer_history.stable.gate import GateVerdict, newest_passing, none_passed
from computer_history.stable.launch_agents import (
    STABLE_AGENTS,
    STOPGAP_LABEL,
    LaunchAgent,
    load_agent,
    remove_agent,
    stopgap_plist,
)
from computer_history.stable.layout import Layout
from computer_history.stable.versions import make_current, pointed, replace_symlink, version_name

NOTHING_CHANGED = "nothing was changed"


class InstallFailed(Exception):
    """Install or uninstall stopped; the message says why and whether anything changed."""


@dataclass(frozen=True)
class InstallReport:
    """What install did: the current version, and the commit it built when it built one."""

    version: str
    built: str | None
    skipped: tuple[GateVerdict, ...]
    retired_stopgap: bool
    loaded: tuple[LaunchAgent, ...]
    link_on_path: bool


@dataclass(frozen=True)
class UninstallReport:
    """The plists, link, pointers and versions folder uninstall removed."""

    removed: tuple[Path, ...]


def install(
    host: Host, layout: Layout, *, path: str, sleep: Callable[[float], None] = time.sleep
) -> InstallReport:
    """Make sure a current version, the PATH link and the LaunchAgents exist, retiring the stopgap.

    With no current version it builds the newest main commit the release gate passes.
    """
    if _taken(layout):
        raise InstallFailed(
            f"{layout.link} already exists and is not the stable install's link; move it"
            f" aside and run install again ({NOTHING_CHANGED})"
        )
    current = pointed(layout.current)
    built, skipped = None, ()
    if current is None:
        try:
            search = newest_passing(host)
            if search.chosen is None:
                raise InstallFailed(f"{none_passed(search.skipped)} ({NOTHING_CHANGED})")
            built, skipped = search.chosen.commit, search.skipped
            make_current(host, layout, built)
        except (HostError, OSError) as exc:
            raise InstallFailed(f"{exc} ({NOTHING_CHANGED})") from exc
    try:
        layout.link.parent.mkdir(parents=True, exist_ok=True)
        replace_symlink(layout.link, layout.command(layout.current))
        retired = remove_agent(host, STOPGAP_LABEL, stopgap_plist(layout))
        for agent in STABLE_AGENTS:
            load_agent(host, layout, agent, sleep=sleep)
    except (HostError, OSError) as exc:
        raise InstallFailed(f"{exc} (run install again to finish)") from exc
    return InstallReport(
        version=current.name if current else version_name(str(built)),
        built=built,
        skipped=skipped,
        retired_stopgap=retired,
        loaded=STABLE_AGENTS,
        link_on_path=link_on_path(layout.link, path),
    )


def link_on_path(link: Path, path: str) -> bool:
    """Whether the link's folder is one of a PATH value's folders, compared once resolved."""
    folder = link.parent.expanduser().resolve()
    return any(
        Path(entry).expanduser().resolve() == folder for entry in path.split(os.pathsep) if entry
    )


def uninstall(host: Host, layout: Layout) -> UninstallReport:
    """Boot out and remove the LaunchAgents, the PATH link, the pointers and every version.

    The database, spool, screenshots, config and logs stay.
    """
    removed: list[Path] = []
    try:
        for agent in STABLE_AGENTS:
            if remove_agent(host, agent.label, agent.plist(layout)):
                removed.append(agent.plist(layout))
        if _ours(layout):
            layout.link.unlink()
            removed.append(layout.link)
        for pointer in (layout.current, layout.previous):
            if pointer.is_symlink():
                pointer.unlink()
                removed.append(pointer)
        if layout.versions.exists():
            shutil.rmtree(layout.versions)
            removed.append(layout.versions)
    except (HostError, OSError) as exc:
        raise InstallFailed(f"{exc} (run uninstall again to finish)") from exc
    return UninstallReport(tuple(removed))


def _ours(layout: Layout) -> bool:
    target = str(layout.command(layout.current))
    return layout.link.is_symlink() and os.readlink(layout.link) == target


def _taken(layout: Layout) -> bool:
    return (layout.link.exists() or layout.link.is_symlink()) and not _ours(layout)
