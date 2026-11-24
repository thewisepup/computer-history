from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import assert_never

from computer_history.host import Host
from computer_history.stable.layout import Layout
from computer_history.stable.versions import (
    InstalledVersion,
    carried_agent,
    stepped,
    version_state,
)
from computer_history.store import replace_atomically


class AgentRecord(Enum):
    NONE = auto()
    UNKNOWN = auto()
    MATCHING = auto()
    STALE = auto()


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
    return _read_record(layout)


def agent_record(
    host: Host, layout: Layout, commit: str
) -> tuple[AgentRecord, InstalledAgent | None]:
    """Whether the installed agent's record says its source matches a commit's, names another, or
    is missing or unreadable, or no app is installed; with the record when there is one."""
    if not layout.capture_agent_app.is_dir():
        return AgentRecord.NONE, None
    installed = _read_record(layout)
    if installed is None:
        return AgentRecord.UNKNOWN, None
    built_from = installed.built_from
    if built_from == commit or host.agent_tree(commit) == host.agent_tree(built_from):
        return AgentRecord.MATCHING, installed
    return AgentRecord.STALE, installed


def _read_record(layout: Layout) -> InstalledAgent | None:
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
    record, installed = agent_record(host, layout, commit)
    match record:
        case AgentRecord.NONE | AgentRecord.UNKNOWN | AgentRecord.STALE:
            return AgentPlan(commit)
        case AgentRecord.MATCHING:
            assert installed is not None, "a matching record was read"
            built_from = installed.built_from
            old_folder = layout.versions / old.name
            if carried_agent(layout, old_folder) == built_from:
                return AgentPlan(built_from, layout.agent_app(old_folder))
            return AgentPlan(built_from, layout.capture_agent_app)
        case _:
            assert_never(record)


def place_agent(host: Host, layout: Layout, plan: AgentPlan, version: Path) -> None:
    """Build or copy the agent app into a version folder with its note, removing both on failure."""
    app, note = layout.agent_app(version), layout.agent_commit(version)
    before = version_state(layout, version)
    try:
        if plan.copy_from is None:
            host.build_agent(plan.built_from, app)
        else:
            shutil.copytree(plan.copy_from, app, symlinks=True)
        note.write_text(f"{plan.built_from}\n", encoding="utf-8")
        stepped(layout, version, before)
    except BaseException:
        shutil.rmtree(app, ignore_errors=True)
        note.unlink(missing_ok=True)
        raise


def keep_installed_app(layout: Layout, version: Path) -> None:
    """Copy the app at the agent's fixed path into a version folder, noting its commit when known,
    unless the folder already carries that app."""
    installed = installed_agent(layout)
    built_from = None if installed is None else installed.built_from
    if built_from is not None and carried_agent(layout, version) == built_from:
        return
    if not layout.capture_agent_app.is_dir():
        return
    app, note = layout.agent_app(version), layout.agent_commit(version)
    before = version_state(layout, version)
    staged = _staged_copy(layout.capture_agent_app, app)
    note.unlink(missing_ok=True)
    shutil.rmtree(app, ignore_errors=True)
    staged.rename(app)
    if built_from is not None:
        note.write_text(f"{built_from}\n", encoding="utf-8")
    stepped(layout, version, before)


def set_aside_fallen_back(layout: Layout, version: Path, restored: Path) -> Path:
    """Move a version folder's agent app and note to its fell-back slot, then copy the restored
    version's app and note into their place; returns the slot."""
    app, note = layout.agent_app(version), layout.agent_commit(version)
    kept, kept_note = layout.fell_back_agent_app(version), layout.fell_back_agent_commit(version)
    before = version_state(layout, version)
    staged = _staged_copy(layout.agent_app(restored), app)
    shutil.rmtree(kept, ignore_errors=True)
    app.rename(kept)
    if note.exists():
        note.replace(kept_note)
    staged.rename(app)
    built_from = carried_agent(layout, restored)
    if built_from is not None:
        note.write_text(f"{built_from}\n", encoding="utf-8")
    stepped(layout, version, before)
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
