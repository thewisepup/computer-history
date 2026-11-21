from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from computer_history.host import ALERT_REPEAT
from computer_history.watchdog.checks import Check, Finding, Reason, Verdict

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


def notices(
    findings: Iterable[Finding],
    *,
    notified: Mapping[Check, datetime],
    open_problems: frozenset[Check],
    silent_after: Mapping[Check, timedelta],
    now: datetime,
) -> list[Notice]:
    """Pick the problems due a notification this hour and the notified problems now cleared."""
    found: list[Notice] = []
    for finding in findings:
        check = finding.check
        if finding.verdict is Verdict.OK and check in open_problems:
            found.append(Notice(check, True, CLEARED[check]))
        last = notified.get(check)
        if finding.verdict is Verdict.PROBLEM and (last is None or now - last >= ALERT_REPEAT):
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
