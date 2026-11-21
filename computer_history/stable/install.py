from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from computer_history.host import Host, HostError
from computer_history.stable.gate import COMMITS_SEARCHED, GateVerdict, newest_passing
from computer_history.stable.launch_agents import (
    STABLE_AGENTS,
    STOPGAP_LABEL,
    LaunchAgent,
    load_agent,
    remove_agent,
    stopgap_plist,
)
from computer_history.stable.layout import Layout
from computer_history.stable.versions import build_version, point, pointed, version_name


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


def install(host: Host, layout: Layout) -> InstallReport:
    """Make sure a current version, the PATH link and the LaunchAgents exist, retiring the stopgap.

    With no current version it builds the newest main commit the release gate passes.
    """
    if _taken(layout):
        raise InstallFailed(
            f"{layout.link} already exists and is not the stable install's link; move it"
            " aside and run install again (nothing was changed)"
        )
    current = pointed(layout.current)
    built, skipped = None, ()
    if current is None:
        try:
            search = newest_passing(host)
            if search.chosen is None:
                raise InstallFailed(f"{_none_passed(search.skipped)} (nothing was changed)")
            built, skipped = search.chosen.commit, search.skipped
            build_version(host, layout, built)
        except HostError as exc:
            raise InstallFailed(f"{exc} (nothing was changed)") from exc
        point(layout.current, version_name(built))
    try:
        _link(layout)
        retired = remove_agent(host, STOPGAP_LABEL, stopgap_plist(layout))
        for agent in STABLE_AGENTS:
            load_agent(host, layout, agent)
    except (HostError, OSError) as exc:
        raise InstallFailed(f"{exc} (run install again to finish)") from exc
    return InstallReport(
        version=current.name if current else version_name(str(built)),
        built=built,
        skipped=skipped,
        retired_stopgap=retired,
        loaded=STABLE_AGENTS,
        link_on_path=str(layout.link.parent) in os.environ.get("PATH", "").split(os.pathsep),
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
    except HostError as exc:
        raise InstallFailed(f"{exc} (run uninstall again to finish)") from exc
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
    return UninstallReport(tuple(removed))


def _none_passed(skipped: tuple[GateVerdict, ...]) -> str:
    found = f"no commit among the newest {COMMITS_SEARCHED} on main passed the release gate"
    if not skipped:
        return f"{found}: main has no commits"
    return f"{found}; the newest, {skipped[0].commit}, has {skipped[0].summary}"


def _target(layout: Layout) -> str:
    return str(layout.command(layout.current))


def _ours(layout: Layout) -> bool:
    return layout.link.is_symlink() and os.readlink(layout.link) == _target(layout)


def _taken(layout: Layout) -> bool:
    return (layout.link.exists() or layout.link.is_symlink()) and not _ours(layout)


def _link(layout: Layout) -> None:
    layout.link.parent.mkdir(parents=True, exist_ok=True)
    staged = layout.link.with_name(f".{layout.link.name}.new")
    staged.unlink(missing_ok=True)
    staged.symlink_to(_target(layout))
    os.replace(staged, layout.link)
