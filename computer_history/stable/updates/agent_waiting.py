from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from computer_history.stable.update_log import AgentOutcome

AGENT_ACTIVE_SECONDS = 120.0
AGENT_WAIT_SECONDS = 600.0
AGENT_POLL_SECONDS = 2.0


NewestAgentRecord = Callable[[], tuple[datetime | None, bool, str | None]]
ActiveBetween = Callable[[datetime, datetime], timedelta | None]


@dataclass(frozen=True)
class AgentCheck:
    """What became of the capture agent in an update, why, and where a fallback kept its build."""

    outcome: AgentOutcome
    detail: str | None = None
    kept: Path | None = None


def wait_for_agent_record(
    newest_record: NewestAgentRecord,
    active_between: ActiveBetween,
    swapped_at: datetime,
    *,
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> AgentCheck:
    """Wait for a record captured since the swap, counting only time the user is active; a pause
    before it, unknown activity or too little of it within the wall-clock bound leaves it
    unverified.

    newest_record gives the newest record's time and whether it marks a pause (None and False
    when there is none), and why the database could not be searched, if it could not.
    """
    deadline = monotonic() + AGENT_WAIT_SECONDS
    while True:
        at, paused, unread = _newest(newest_record)
        if at is not None and at >= swapped_at:
            return AgentCheck(AgentOutcome.VERIFIED, "the new capture agent records")
        if paused:
            return AgentCheck(AgentOutcome.NOT_VERIFIED, "capture is paused")
        try:
            attended = active_between(swapped_at, now())
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


def _newest(newest_record: NewestAgentRecord) -> tuple[datetime | None, bool, str | None]:
    try:
        return newest_record()
    except (OSError, ValueError, sqlite3.Error) as exc:
        return None, False, f"the database could not be read ({exc})"
