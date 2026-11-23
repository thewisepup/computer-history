from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from computer_history.host import Host
from computer_history.stable.layout import Layout
from computer_history.stable.versions import InstalledVersion
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


def installed_agent(layout: Layout) -> InstalledAgent | None:
    """The installed agent's record, or None when it is missing or unreadable or its app is gone."""
    if not layout.capture_agent_app.is_dir():
        return None
    try:
        data = json.loads(layout.installed_agent.read_text(encoding="utf-8"))
        return InstalledAgent(
            str(data["built_from"]), datetime.fromisoformat(str(data["installed_at"]))
        )
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return None


def record_installed_agent(layout: Layout, built_from: str, installed_at: datetime) -> None:
    """Note which commit the app now at the agent's fixed path was built from."""
    line = json.dumps({"built_from": built_from, "installed_at": installed_at.isoformat()})
    replace_atomically(
        layout.installed_agent, lambda staged: staged.write_text(f"{line}\n", encoding="utf-8")
    )


def record_installed_agent_or_note(
    layout: Layout, built_from: str, installed_at: datetime, problems: list[str]
) -> None:
    """Record the installed agent's commit, noting a failed write among the problems."""
    try:
        record_installed_agent(layout, built_from, installed_at)
    except OSError as exc:
        problems.append(f"the installed agent's record could not be written: {exc}")


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


def keep_installed_app(layout: Layout, version: Path) -> None:
    """Copy the app at the agent's fixed path into a version folder, noting its commit when known,
    unless the folder already carries that app."""
    installed = installed_agent(layout)
    built_from = None if installed is None else installed.built_from
    if built_from is not None and _note(layout, version) == built_from:
        return
    if not layout.capture_agent_app.is_dir():
        return
    app, note = layout.agent_app(version), layout.agent_commit(version)
    staged = _staged_copy(layout.capture_agent_app, app)
    note.unlink(missing_ok=True)
    shutil.rmtree(app, ignore_errors=True)
    staged.rename(app)
    if built_from is not None:
        note.write_text(f"{built_from}\n", encoding="utf-8")


def set_aside_fallen_back(layout: Layout, version: Path, restored: Path) -> Path:
    """Move a version folder's agent app and note to its fell-back slot, then copy the restored
    version's app and note into their place; returns the slot."""
    app, note = layout.agent_app(version), layout.agent_commit(version)
    kept, kept_note = layout.fell_back_agent_app(version), layout.fell_back_agent_commit(version)
    staged = _staged_copy(layout.agent_app(restored), app)
    shutil.rmtree(kept, ignore_errors=True)
    app.rename(kept)
    if note.exists():
        note.replace(kept_note)
    staged.rename(app)
    built_from = _note(layout, restored)
    if built_from is not None:
        note.write_text(f"{built_from}\n", encoding="utf-8")
    return kept


def _staged_copy(source: Path, app: Path) -> Path:
    staged = app.with_name(f".{app.name}.staged")
    shutil.rmtree(staged, ignore_errors=True)
    try:
        shutil.copytree(source, staged, symlinks=True)
    except BaseException:
        shutil.rmtree(staged, ignore_errors=True)
        raise
    return staged


def carried_agent(layout: Layout, version: Path) -> str | None:
    """The commit a version folder's agent app was built from, or None without an app or note."""
    return _note(layout, version)


def _note(layout: Layout, version: Path) -> str | None:
    if not layout.agent_app(version).is_dir():
        return None
    try:
        return layout.agent_commit(version).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None
