"""The watchdog: every minute, is anything that records Brandon's activity silent?

run.py          one run, under a lock: read the thresholds and the last state,
    |           check, notify through the host adapter, save the state
    +-- thresholds.py  how long each subject may stay silent, from the
    |                  watchdog object in the agent's config file
    +-- reopening.py   open ActivityWatch when its app is down, at most
    |                  three times an hour
    +-- assessment.py  gather what the checks judge from (the spool, the
    |   |              database, ActivityWatch, the ingest health file) and
    |   |              judge all three, for a run and for status alike
    |   +-- checks.py  judge the capture agent (its newest record and its
    |                  liveness), ActivityWatch (reachable, sources advancing)
    |                  and the backend (silent: no cycle in its ingest health
    |                  file; failing cycles alert from ingest itself)
    +-- alerts.py      which findings notify: a problem at most once an hour,
    |                  a clear once, each check's alert closed or open, the
    |                  notification text, and which errors are due a log line
    +-- state.py       the state file and lock beside the database: the last
                       findings, what was notified and logged, the reopens,
                       when watching resumed, and whether the watchdog stopped
"""

from computer_history.watchdog.assessment import Assessment, assess
from computer_history.watchdog.checks import Check, Finding, Reason, Verdict
from computer_history.watchdog.reopening import REOPEN_LIMIT, recent_reopens
from computer_history.watchdog.run import WatchdogRun, WatchPaths, watch_once
from computer_history.watchdog.state import (
    WatchdogState,
    read_state_or_fresh,
    running_since,
    stopped,
    watchdog_lock_path,
    watchdog_state_path,
)
from computer_history.watchdog.thresholds import read_thresholds

__all__ = [
    "REOPEN_LIMIT",
    "Assessment",
    "Check",
    "Finding",
    "Reason",
    "Verdict",
    "WatchPaths",
    "WatchdogRun",
    "WatchdogState",
    "assess",
    "read_state_or_fresh",
    "read_thresholds",
    "recent_reopens",
    "running_since",
    "stopped",
    "watch_once",
    "watchdog_lock_path",
    "watchdog_state_path",
]
