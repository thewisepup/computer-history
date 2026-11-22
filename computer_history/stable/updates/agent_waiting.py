from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from computer_history.stable.update_log import AgentOutcome

AGENT_ACTIVE_SECONDS = 120.0
AGENT_WAIT_SECONDS = 600.0
AGENT_POLL_SECONDS = 2.0


class SeenRecord(Protocol):
    """The capture agent's newest record: when it was captured, and whether it marks a pause."""

    @property
    def at(self) -> datetime: ...

    @property
    def paused(self) -> bool: ...


class NewestSeen(Protocol):
    """The capture agent's newest record found, and why the database could not be searched for
    one, if it could not."""

    @property
    def record(self) -> SeenRecord | None: ...

    @property
    def database_unread(self) -> str | None: ...


class AgentRecords(Protocol):
    """The capture agent's newest record, stored or in the spool, and how long aw-afk shows the
    user active between two times (None when ActivityWatch can't say)."""

    def newest_record(self) -> NewestSeen: ...

    def active_between(self, start: datetime, end: datetime) -> timedelta | None: ...


@dataclass(frozen=True)
class AgentCheck:
    """What became of the capture agent in an update, why, and where a fallback kept its build."""

    outcome: AgentOutcome
    detail: str | None = None
    kept: Path | None = None


def wait_for_agent_record(
    records: AgentRecords,
    swapped_at: datetime,
    *,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> AgentCheck:
    """Wait for a record captured since the swap, counting only time the user is active; a pause
    before it, unknown activity or too little of it within the wall-clock bound leaves it
    unverified."""
    deadline = monotonic() + AGENT_WAIT_SECONDS
    while True:
        newest, unread = _newest(records)
        if newest is not None and newest.at >= swapped_at:
            return AgentCheck(AgentOutcome.VERIFIED, "the new capture agent records")
        if newest is not None and newest.paused:
            return AgentCheck(AgentOutcome.NOT_VERIFIED, "capture is paused")
        try:
            attended = records.active_between(swapped_at, now())
        except (OSError, ValueError, sqlite3.Error) as exc:
            return AgentCheck(
                AgentOutcome.NOT_VERIFIED, f"your activity since the swap could not be read: {exc}"
            )
        if attended is None:
            return AgentCheck(
                AgentOutcome.NOT_VERIFIED, "ActivityWatch could not say whether you were active"
            )
        if attended.total_seconds() >= AGENT_ACTIVE_SECONDS:
            silent = (
                f"the new capture agent recorded nothing in {AGENT_ACTIVE_SECONDS:g}s while you"
                " were active"
            )
            if unread is not None:
                return AgentCheck(
                    AgentOutcome.NOT_VERIFIED,
                    f"{silent}, but {unread}, so only the spool was checked",
                )
            return AgentCheck(AgentOutcome.FELL_BACK, silent)
        if monotonic() >= deadline:
            return AgentCheck(
                AgentOutcome.NOT_VERIFIED,
                f"you were not active for {AGENT_ACTIVE_SECONDS:g}s within the"
                f" {AGENT_WAIT_SECONDS:g}s wait",
            )
        sleep(AGENT_POLL_SECONDS)


def _newest(records: AgentRecords) -> tuple[SeenRecord | None, str | None]:
    try:
        seen = records.newest_record()
    except (OSError, ValueError, sqlite3.Error) as exc:
        return None, f"the database could not be read ({exc})"
    return seen.record, seen.database_unread
