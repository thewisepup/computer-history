"""The watchdog: every minute, is anything that records Brandon's activity silent?

run.py          one run: read the thresholds and the last state, reopen
    |           ActivityWatch if it is down (at most three times an hour),
    |           check, notify through the host adapter, save the state
    +-- thresholds.py  how long each subject may stay silent, from the
    |                  watchdog object in the agent's config file
    +-- checks.py      judge the capture agent (its newest record and status's
    |                  liveness), ActivityWatch (reachable, buckets advancing)
    |                  and the backend (its heartbeat)
    +-- alerts.py      which findings notify: a problem at most once an hour,
    |                  a clear once, and the notification text
    +-- state.py       the state file beside the database: the last findings,
                       what was notified, the reopens, when watching resumed
"""

from computer_history.watchdog.alerts import (
    NOTIFICATION_TITLE,
    REOPEN_LIMIT,
    REOPEN_WINDOW,
    Notice,
)
from computer_history.watchdog.checks import Check, Finding, Reason, Verdict
from computer_history.watchdog.run import WATCH_GAP, WatchdogRun, WatchPaths, watch_once
from computer_history.watchdog.state import (
    WatchdogState,
    read_watchdog_state,
    watchdog_state_path,
)
from computer_history.watchdog.thresholds import DEFAULT_SILENT_MINUTES, Thresholds

__all__ = [
    "DEFAULT_SILENT_MINUTES",
    "NOTIFICATION_TITLE",
    "REOPEN_LIMIT",
    "REOPEN_WINDOW",
    "WATCH_GAP",
    "Check",
    "Finding",
    "Notice",
    "Reason",
    "Thresholds",
    "Verdict",
    "WatchPaths",
    "WatchdogRun",
    "WatchdogState",
    "read_watchdog_state",
    "watch_once",
    "watchdog_state_path",
]
