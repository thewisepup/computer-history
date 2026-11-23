from __future__ import annotations

import fcntl
import json
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from computer_history.store import replace_atomically
from computer_history.watchdog.checks import Check, Finding, Reason, Verdict

WATCHDOG_STATE_NAME = "watchdog.json"
WATCHDOG_LOCK_NAME = ".watchdog.lock"
WATCH_GAP = timedelta(minutes=3)


@dataclass(frozen=True)
class WatchdogState:
    """What the watchdog remembers between runs, and the findings and errors of its last run."""

    ran_at: datetime | None = None
    watching_since: datetime | None = None
    findings: tuple[Finding, ...] = ()
    notified: dict[Check, datetime] = field(default_factory=lambda: {})
    open: frozenset[Check] = frozenset()
    reopened: tuple[datetime, ...] = ()
    unreachable_since: datetime | None = None
    logged: dict[str, datetime] = field(default_factory=lambda: {})
    errors: tuple[str, ...] = ()


def stopped(state: WatchdogState, now: datetime) -> bool:
    """Whether the watchdog has gone longer without a run than its every-minute schedule allows."""
    return state.ran_at is None or now - state.ran_at > WATCH_GAP


def running_since(state: WatchdogState, now: datetime) -> datetime | None:
    """When a still-running watchdog began watching, or None when it has stopped."""
    return None if stopped(state, now) else state.watching_since


def read_state_or_fresh(path: Path) -> tuple[WatchdogState, str | None]:
    """Read the saved state, or a fresh one with why when the file is unreadable."""
    try:
        return read_watchdog_state(path) or WatchdogState(), None
    except (OSError, ValueError) as exc:
        return WatchdogState(), str(exc)


def watchdog_state_path(db_path: Path) -> Path:
    """Find the watchdog's state file beside the database it watches."""
    return db_path.parent / WATCHDOG_STATE_NAME


def watchdog_lock_path(db_path: Path) -> Path:
    """Find the lock file a watchdog run holds, beside the database it watches."""
    return db_path.parent / WATCHDOG_LOCK_NAME


@contextmanager
def holding(lock: Path) -> Generator[bool, None, None]:
    """Hold the lock file for the duration, yielding False when another run already holds it."""
    with lock.open("a") as held:
        try:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(held, fcntl.LOCK_UN)


def read_watchdog_state(path: Path) -> WatchdogState | None:
    """Read the state the last run saved, or None when no run saved one."""
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
            logged={str(message): _required(at) for message, at in saved["logged"].items()},
            errors=tuple(str(error) for error in saved["errors"]),
        )
    except (KeyError, TypeError, AttributeError, RecursionError) as exc:
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
        "logged": {message: at.isoformat() for message, at in state.logged.items()},
        "errors": list(state.errors),
    }
    text = json.dumps(saved, indent=1)
    replace_atomically(path, lambda staged: staged.write_text(text, encoding="utf-8"))


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
