from __future__ import annotations

import json
from collections.abc import Iterator
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

    @property
    def moves_current(self) -> bool:
        return self in (UpdateAction.UPDATED, UpdateAction.FELL_BACK, UpdateAction.ROLLED_BACK)


class AgentOutcome(Enum):
    UNCHANGED = "unchanged"
    VERIFIED = "updated and verified"
    NOT_VERIFIED = "installed, not verified"
    FELL_BACK = "fell back"
    NOT_SWAPPED = "not swapped"


_CLEARS_A_FALLBACK = (AgentOutcome.UNCHANGED, AgentOutcome.VERIFIED, AgentOutcome.NOT_VERIFIED)


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


def last_update_log_entry(path: Path) -> UpdateLogEntry | None:
    """The update log's last line that moved current, skipping agent lines and lines a newer
    version wrote, or None without one; ValueError when a line it reaches is unreadable."""
    return next((entry for entry in _newest_first(path) if entry.action.moves_current), None)


def last_agent_fallback(path: Path) -> UpdateLogEntry | None:
    """The update log's last agent fallback, unless a later update or rollback installed or kept
    an agent; ValueError when a line it reaches is unreadable."""
    for entry in _newest_first(path):
        if entry.action is UpdateAction.AGENT_FELL_BACK:
            return entry
        if entry.action is UpdateAction.AGENT_ROLLED_BACK or entry.agent in _CLEARS_A_FALLBACK:
            return None
    return None


def _newest_first(path: Path) -> Iterator[UpdateLogEntry]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for number in range(len(lines), 0, -1):
        entry = _entry(path, number, lines[number - 1])
        if entry is not None:
            yield entry


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
