from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from computer_history.host import Host, SpoolReads
from computer_history.stable.layout import Layout
from computer_history.stable.versions import InstalledVersion, version_name
from computer_history.store import INSTALL_MARKER_NAME, replace_atomically


@dataclass(frozen=True)
class InstalledAgent:
    """The commit the app at the agent's fixed path was built from, and when it went there."""

    built_from: str
    installed_at: datetime


@dataclass(frozen=True)
class AgentPlan:
    """The commit the new version's agent app comes from, and the app to copy if unchanged."""

    built_from: str
    copy_from: Path | None = None

    @property
    def changed(self) -> bool:
        return self.copy_from is None


@dataclass(frozen=True)
class AgentMove:
    """Rollback's move of the capture agent to the app a version folder carries, and why."""

    app: Path
    built_from: str
    from_version: str
    to_version: str
    reason: str


@dataclass(frozen=True)
class AgentRollback:
    """Whether rollback moved the capture agent, and why when it could tell."""

    moved: bool
    why: str | None = None


def installed_agent(layout: Layout) -> InstalledAgent | None:
    """The installed agent's record, or None when it is missing or unreadable or its app is gone."""
    if not layout.capture_agent_app.is_dir():
        return None
    try:
        data = json.loads(layout.installed_agent.read_text(encoding="utf-8"))
        return InstalledAgent(
            str(data["built_from"]), datetime.fromisoformat(str(data["installed_at"]))
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None


def record_installed_agent(layout: Layout, built_from: str, installed_at: datetime) -> None:
    """Note which commit the app now at the agent's fixed path was built from."""
    line = json.dumps({"built_from": built_from, "installed_at": installed_at.isoformat()})
    replace_atomically(
        layout.installed_agent, lambda staged: staged.write_text(f"{line}\n", encoding="utf-8")
    )


def plan_agent(host: Host, layout: Layout, commit: str, old: InstalledVersion) -> AgentPlan:
    """Build the agent from the commit when its source differs from the installed agent's or that
    is unknown; otherwise copy the installed agent's app, from the old version when it holds it."""
    installed = installed_agent(layout)
    if installed is None:
        return AgentPlan(commit)
    built_from = installed.built_from
    if built_from != commit and host.agent_tree(commit) != host.agent_tree(built_from):
        return AgentPlan(commit)
    old_folder = layout.versions / old.name
    if _note(layout, old_folder) == built_from:
        return AgentPlan(built_from, layout.agent_app(old_folder))
    return AgentPlan(built_from, layout.capture_agent_app)


def plan_agent_rollback(
    layout: Layout, target: str, problems: list[str]
) -> AgentMove | AgentRollback:
    """Move the agent to the target version's app when the target can't read every record kind
    the installed agent writes; leave it, noting a problem, when either side is unknown."""
    installed = installed_agent(layout)
    if installed is None:
        problems.append(
            "could not tell which build the installed capture agent is; it was left as it is"
        )
        return AgentRollback(moved=False)
    built_from = installed.built_from
    folder = layout.versions / target
    note = _note(layout, folder)
    if note == built_from:
        return AgentRollback(moved=False, why=f"{target} carries the same build")
    target_reads = _spool_reads(layout, folder)
    if target_reads is None:
        problems.append(
            f"could not tell which record kinds {target} reads; the capture agent was left as it is"
        )
        return AgentRollback(moved=False)
    carrying = _carrying(layout, built_from)
    writes = None if carrying is None else _spool_reads(layout, carrying)
    if carrying is None or writes is None:
        source = "installed" if carrying is None else f"from {carrying.name}"
        problems.append(
            f"could not tell which record kinds the capture agent {source} writes; it was left as"
            " it is"
        )
        return AgentRollback(moved=False)
    reason = _unread(target, target_reads, writes)
    if reason is None:
        return AgentRollback(moved=False, why=f"{target} reads every record kind it writes")
    if note is None:
        problems.append(
            f"could not move the capture agent back: {reason}, but {target} carries no agent"
            " app; it was left as it is"
        )
        return AgentRollback(moved=False)
    return AgentMove(layout.agent_app(folder), note, carrying.name, target, reason)


def holds_agent(layout: Layout, version: Path) -> bool:
    """Whether a marked version folder already carries its agent app and the note of its commit."""
    return (version / INSTALL_MARKER_NAME).is_file() and _note(layout, version) is not None


def place_agent(host: Host, layout: Layout, plan: AgentPlan, version: Path) -> None:
    """Build or copy the agent app into a version folder with its note, removing both on failure."""
    app, note = layout.agent_app(version), layout.agent_commit(version)
    try:
        if plan.copy_from is None:
            host.build_agent(plan.built_from, app)
        else:
            shutil.copytree(plan.copy_from, app, symlinks=True)
        note.write_text(f"{plan.built_from}\n", encoding="utf-8")
    except BaseException:
        shutil.rmtree(app, ignore_errors=True)
        note.unlink(missing_ok=True)
        raise


def _note(layout: Layout, version: Path) -> str | None:
    if not layout.agent_app(version).is_dir():
        return None
    try:
        return layout.agent_commit(version).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _spool_reads(layout: Layout, version: Path) -> SpoolReads | None:
    try:
        return SpoolReads.from_json(layout.spool_reads(version).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _carrying(layout: Layout, built_from: str) -> Path | None:
    try:
        folders = sorted(layout.versions.iterdir())
    except OSError:
        return None
    found = [f for f in folders if holds_agent(layout, f) and _note(layout, f) == built_from]
    return min(found, key=lambda folder: folder.name != version_name(built_from), default=None)


def _unread(target: str, reads: SpoolReads, writes: SpoolReads) -> str | None:
    if reads.version != writes.version:
        return f"{target} reads spool v{reads.version}, it writes v{writes.version}"
    missing = [kind for kind in writes.kinds if kind not in reads.kinds]
    if not missing:
        return None
    return f"{target} does not read its {', '.join(missing)} records"
