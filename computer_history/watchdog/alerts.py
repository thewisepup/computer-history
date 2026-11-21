from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from computer_history.watchdog.checks import Check, Finding, Reason, Verdict

NOTIFICATION_TITLE = "Computer History"
NOTIFY_EVERY = timedelta(hours=1)
REOPEN_LIMIT = 3
REOPEN_WINDOW = timedelta(hours=1)
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
    """A problem notifies at most once an hour, and a notified problem notifies once when it clears.

    A check that cannot tell neither notifies nor clears.
    """
    found: list[Notice] = []
    for finding in findings:
        check = finding.check
        if finding.verdict is Verdict.OK and check in open_problems:
            found.append(Notice(check, True, CLEARED[check]))
        last = notified.get(check)
        if finding.verdict is Verdict.PROBLEM and (last is None or now - last >= NOTIFY_EVERY):
            found.append(Notice(check, False, problem_message(finding, silent_after[check])))
    return found


def problem_message(finding: Finding, silent_after: timedelta) -> str:
    """The notification text for a problem, naming the threshold it passed."""
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


def recent_reopens(reopened: Iterable[datetime], now: datetime) -> tuple[datetime, ...]:
    """The reopens of ActivityWatch inside the window the limit counts."""
    return tuple(at for at in reopened if now - at < REOPEN_WINDOW)
