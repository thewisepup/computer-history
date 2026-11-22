from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class UpdateAction(Enum):
    UPDATED = "updated"
    FELL_BACK = "fell back"
    ROLLED_BACK = "rolled back"
    AGENT_FELL_BACK = "agent fell back"
    AGENT_ROLLED_BACK = "agent rolled back"


class AgentOutcome(Enum):
    UNCHANGED = "unchanged"
    VERIFIED = "updated and verified"
    NOT_VERIFIED = "installed, not verified"
    FELL_BACK = "fell back"


@dataclass(frozen=True)
class UpdateLogEntry:
    """One update log line: what moved current or the capture agent, from which version to which,
    why, and what an update did to the agent."""

    at: datetime
    action: UpdateAction
    from_version: str
    to_version: str
    reason: str | None = None
    agent: AgentOutcome | None = None


def append_update_log(path: Path, entry: UpdateLogEntry) -> None:
    """Add one JSON line to the update log, creating it if needed."""
    line = {
        "at": entry.at.isoformat(),
        "action": entry.action.value,
        "from": entry.from_version,
        "to": entry.to_version,
        "reason": entry.reason,
    }
    if entry.agent is not None:
        line["agent"] = entry.agent.value
    with path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(line) + "\n")


def last_update_log_entry(path: Path, action: UpdateAction | None = None) -> UpdateLogEntry | None:
    """The update log's last line with an action this version knows, or with the given action,
    skipping lines a newer one wrote, or None without one; ValueError when a line it reaches is
    unreadable."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return None
    for number in range(len(lines), 0, -1):
        entry = _entry(path, number, lines[number - 1])
        if entry is not None and action in (None, entry.action):
            return entry
    return None


def _entry(path: Path, number: int, line: str) -> UpdateLogEntry | None:
    problem = f"line {number} of {path} is not an update log entry"
    try:
        written = json.loads(line)
        known = {action.value for action in UpdateAction}
        if isinstance(written["action"], str) and written["action"] not in known:
            return None
        at = datetime.fromisoformat(written["at"])
        action = UpdateAction(written["action"])
        from_version, to_version, reason = written["from"], written["to"], written.get("reason")
        outcomes = {outcome.value: outcome for outcome in AgentOutcome}
        agent = outcomes.get(written.get("agent"))
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError(problem) from exc
    names = (from_version, to_version)
    if at.tzinfo is None or not all(isinstance(name, str) for name in names):
        raise ValueError(problem)
    if reason is not None and not isinstance(reason, str):
        raise ValueError(problem)
    return UpdateLogEntry(at, action, from_version, to_version, reason, agent)


def append_or_note(path: Path, entry: UpdateLogEntry, problems: list[str]) -> None:
    """Add the entry to the update log, noting a failed write among the problems."""
    try:
        append_update_log(path, entry)
    except OSError as exc:
        problems.append(f"the update log could not be written: {exc}")
