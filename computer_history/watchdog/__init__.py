"""The watchdog: every minute, is anything that records Brandon's activity silent?

run.py          one run, under a lock: read the thresholds and the last state,
    |           check, notify through the host adapter, save the state
    +-- thresholds.py  how long each subject may stay silent, from the
    |                  watchdog object in the agent's config file
    +-- reopening.py   open ActivityWatch when its app is down, at most
    |                  three times an hour
    +-- checks.py      judge the capture agent (its newest record and status's
    |                  liveness), ActivityWatch (reachable, sources advancing)
    |                  and the backend (silent: no cycle in its ingest health
    |                  file; failing cycles alert from ingest itself)
    +-- alerts.py      which findings notify: a problem at most once an hour,
    |                  a clear once, the notification text, and which errors
    |                  are due a log line
    +-- state.py       the state file and lock beside the database: the last
                       findings, what was notified and logged, the reopens,
                       when watching resumed
"""

from computer_history.watchdog.checks import Check, Finding, Reason, Verdict
from computer_history.watchdog.reopening import REOPEN_LIMIT, recent_reopens
from computer_history.watchdog.run import WatchdogRun, WatchPaths, stopped, watch_once
from computer_history.watchdog.state import (
    read_watchdog_state,
    watchdog_lock_path,
    watchdog_state_path,
)

__all__ = [
    "REOPEN_LIMIT",
    "Check",
    "Finding",
    "Reason",
    "Verdict",
    "WatchPaths",
    "WatchdogRun",
    "read_watchdog_state",
    "recent_reopens",
    "stopped",
    "watch_once",
    "watchdog_lock_path",
    "watchdog_state_path",
]
