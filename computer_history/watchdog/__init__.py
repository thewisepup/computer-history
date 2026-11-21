"""The watchdog: every minute, is anything that records Brandon's activity silent?

run.py          one run, under a lock: read the thresholds and the last state,
    |           check, notify through the host adapter, save the state
    +-- thresholds.py  how long each subject may stay silent, from the
    |                  watchdog object in the agent's config file
    +-- reopening.py   open ActivityWatch when its app is down, at most
    |                  three times an hour
    +-- checks.py      judge the capture agent (its newest record and status's
    |                  liveness), ActivityWatch (reachable, sources advancing)
    |                  and the backend (its heartbeat: silent or failing)
    +-- alerts.py      which findings notify: a problem at most once an hour,
    |                  a clear once, the notification text, and which errors
    |                  are due a log line
    +-- state.py       the state file and lock beside the database: the last
                       findings, what was notified and logged, the reopens,
                       when watching resumed
"""

from computer_history.watchdog.alerts import NOTIFICATION_TITLE, Notice
from computer_history.watchdog.checks import Check, Finding, Reason, Verdict
from computer_history.watchdog.reopening import REOPEN_LIMIT, Reopening, recent_reopens
from computer_history.watchdog.run import WatchdogRun, WatchPaths, stopped, watch_once
from computer_history.watchdog.state import (
    WatchdogState,
    read_watchdog_state,
    watchdog_lock_path,
    watchdog_state_path,
)
from computer_history.watchdog.thresholds import Thresholds

__all__ = [
    "NOTIFICATION_TITLE",
    "REOPEN_LIMIT",
    "Check",
    "Finding",
    "Notice",
    "Reason",
    "Reopening",
    "Thresholds",
    "Verdict",
    "WatchPaths",
    "WatchdogRun",
    "WatchdogState",
    "read_watchdog_state",
    "recent_reopens",
    "stopped",
    "watch_once",
    "watchdog_lock_path",
    "watchdog_state_path",
]
