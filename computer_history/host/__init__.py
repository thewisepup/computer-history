"""The host adapter: the one seam to macOS and the network.

    contract.py   Host (the Protocol), its answers (CheckRun, JobState), HostError
                  and JobBusy (launchd not done with a job yet), the command
                  that opens ActivityWatch, and how often a lasting problem may
                  notify again
        |
    live.py       LiveHost: launchctl in the login session, GitHub's public API
                  for check runs on main, uv for building a stable version,
                  pgrep and open for ActivityWatch, osascript for notifications
                  under the one title, off when $COMPUTER_HISTORY_NOTIFY is 0

Commands build a LiveHost and pass it down; tests pass a fake that records calls.
"""

from computer_history.host.contract import (
    ALERT_REPEAT,
    COMMAND_NAME,
    OPEN_ACTIVITYWATCH,
    CheckOutcome,
    CheckRun,
    Host,
    HostError,
    JobBusy,
    JobState,
)
from computer_history.host.live import NOTIFY_ENV_VAR, LiveHost

__all__ = [
    "ALERT_REPEAT",
    "COMMAND_NAME",
    "NOTIFY_ENV_VAR",
    "OPEN_ACTIVITYWATCH",
    "CheckOutcome",
    "CheckRun",
    "Host",
    "HostError",
    "JobBusy",
    "JobState",
    "LiveHost",
]
