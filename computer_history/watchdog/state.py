from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from computer_history.watchdog.checks import Check, Finding, Reason, Verdict

WATCHDOG_STATE_NAME = "watchdog.json"


@dataclass(frozen=True)
class WatchdogState:
    """What the watchdog remembers between runs, and the findings of its last run.

    Notified holds each check's last problem notification, and open the problems not yet cleared.
    """

    ran_at: datetime | None = None
    watching_since: datetime | None = None
    findings: tuple[Finding, ...] = ()
    notified: dict[Check, datetime] = field(default_factory=lambda: {})
    open: frozenset[Check] = frozenset()
    reopened: tuple[datetime, ...] = ()
    unreachable_since: datetime | None = None
    errors: tuple[str, ...] = ()


def watchdog_state_path(db_path: Path) -> Path:
    """The watchdog's state file sits beside the database it watches."""
    return db_path.parent / WATCHDOG_STATE_NAME


def read_watchdog_state(path: Path) -> WatchdogState | None:
    """The state the last run wrote, or None when no run wrote one."""
    if not path.exists():
        return None
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        return WatchdogState(
            ran_at=_time(saved["ran_at"]),
            watching_since=_time(saved["watching_since"]),
            findings=tuple(_finding(found) for found in saved["findings"]),
            notified={Check(name): _required(at) for name, at in saved["notified"].items()},
            open=frozenset(Check(name) for name in saved["open"]),
            reopened=tuple(_required(at) for at in saved["reopened"]),
            unreachable_since=_time(saved["unreachable_since"]),
            errors=tuple(str(error) for error in saved["errors"]),
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"{path} is not the watchdog's state: {exc!r}") from exc


def write_watchdog_state(path: Path, state: WatchdogState) -> None:
    """Replace the state file in one step."""
    saved = {
        "ran_at": _iso(state.ran_at),
        "watching_since": _iso(state.watching_since),
        "findings": [
            {
                "check": found.check.value,
                "verdict": found.verdict.value,
                "reason": found.reason.value,
                "last_seen": _iso(found.last_seen),
                "detail": found.detail,
            }
            for found in state.findings
        ],
        "notified": {check.value: at.isoformat() for check, at in state.notified.items()},
        "open": sorted(check.value for check in state.open),
        "reopened": [at.isoformat() for at in state.reopened],
        "unreachable_since": _iso(state.unreachable_since),
        "errors": list(state.errors),
    }
    staged = path.with_name(f".{path.name}.new")
    staged.write_text(json.dumps(saved, indent=1), encoding="utf-8")
    os.replace(staged, path)


def _finding(saved: dict[str, Any]) -> Finding:
    detail = saved["detail"]
    return Finding(
        Check(saved["check"]),
        Verdict(saved["verdict"]),
        Reason(saved["reason"]),
        _time(saved["last_seen"]),
        None if detail is None else str(detail),
    )


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _time(value: Any) -> datetime | None:
    return None if value is None else _required(value)


def _required(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError(f"{value!r} has no time zone")
    return parsed
