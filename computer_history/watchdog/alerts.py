from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import assert_never

from computer_history.host import ALERT_REPEAT
from computer_history.transitions import TransitionTable
from computer_history.watchdog.checks import Check, Finding, Reason, Verdict


class AlertState(Enum):
    CLOSED = auto()
    OPEN_NOTIFIED = auto()


ALERTS = TransitionTable(
    "watchdog alert",
    {
        AlertState.CLOSED: frozenset({AlertState.OPEN_NOTIFIED}),
        AlertState.OPEN_NOTIFIED: frozenset({AlertState.OPEN_NOTIFIED, AlertState.CLOSED}),
    },
)

SUBJECTS = {
    Check.CAPTURE_AGENT: "The capture agent",
    Check.ACTIVITYWATCH: "ActivityWatch",
    Check.BACKEND: "The backend",
}
CLEARED = {
    Check.CAPTURE_AGENT: "The capture agent is recording again.",
    Check.ACTIVITYWATCH: "ActivityWatch is recording again.",
    Check.BACKEND: "The backend is finishing ingest cycles again.",
}


@dataclass(frozen=True)
class Notice:
    """A notification to post: a problem found, or a notified problem cleared."""

    check: Check
    cleared: bool
    message: str


def alert_state(notified: Mapping[Check, datetime], check: Check) -> AlertState:
    """Whether a check has a notified problem still open."""
    return AlertState.OPEN_NOTIFIED if check in notified else AlertState.CLOSED


def record_notice(notified: dict[Check, datetime], notice: Notice, now: datetime) -> None:
    """Note a posted notice: a problem stays open as notified now, a clear closes it."""
    target = AlertState.CLOSED if notice.cleared else AlertState.OPEN_NOTIFIED
    moved = ALERTS.move(alert_state(notified, notice.check), target)
    match moved:
        case AlertState.CLOSED:
            del notified[notice.check]
        case AlertState.OPEN_NOTIFIED:
            notified[notice.check] = now
        case _:
            assert_never(moved)


def notices(
    findings: Iterable[Finding],
    *,
    notified: Mapping[Check, datetime],
    silent_after: Mapping[Check, timedelta],
    now: datetime,
) -> list[Notice]:
    """Pick the problems due a notification this hour and the notified problems now cleared."""
    found: list[Notice] = []
    for finding in findings:
        check = finding.check
        state = alert_state(notified, check)
        match state:
            case AlertState.CLOSED:
                due = finding.verdict is Verdict.PROBLEM
            case AlertState.OPEN_NOTIFIED:
                if finding.verdict is Verdict.OK:
                    found.append(Notice(check, True, CLEARED[check]))
                due = finding.verdict is Verdict.PROBLEM and now - notified[check] >= ALERT_REPEAT
            case _:
                assert_never(state)
        if due:
            found.append(Notice(check, False, _problem_message(finding, silent_after[check])))
    return found


def due_to_log(
    messages: Iterable[str], logged: Mapping[str, datetime], now: datetime
) -> tuple[tuple[str, ...], dict[str, datetime]]:
    """Pick the messages not logged in the last hour, and when each message was last logged."""
    kept = {message: at for message, at in logged.items() if now - at < ALERT_REPEAT}
    due = tuple(dict.fromkeys(message for message in messages if message not in kept))
    return due, kept | {message: now for message in due}


def _problem_message(finding: Finding, silent_after: timedelta) -> str:
    minutes = f"{silent_after.total_seconds() / 60:g} min"
    subject = SUBJECTS[finding.check]
    match finding.reason:
        case Reason.UNREACHABLE:
            return f"{subject} has been unreachable for over {minutes}."
        case Reason.STALLED:
            return f"{subject} has recorded nothing for over {minutes} in {finding.detail}."
        case _ if finding.check is Check.BACKEND:
            return (
                f"{subject} has finished no ingest cycle for over {minutes} while you were active."
            )
        case _:
            return f"{subject} has recorded nothing for over {minutes} while you were active."
