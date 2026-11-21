"""The host adapter: the one seam to macOS and the network.

    contract.py   Host (the Protocol), its answers (CheckRun, JobState), HostError
                  and JobBusy (launchd not done with a job yet), and the command
                  that opens ActivityWatch
        |
    live.py       LiveHost: launchctl in the login session, GitHub's public API
                  for check runs on main, uv for building a stable version,
                  pgrep and open for ActivityWatch, osascript for notifications

Commands build a LiveHost and pass it down; tests pass a fake that records calls.
"""

from computer_history.host.contract import (
    COMMAND_NAME,
    OPEN_ACTIVITYWATCH,
    CheckOutcome,
    CheckRun,
    Host,
    HostError,
    JobBusy,
    JobState,
)
from computer_history.host.live import LiveHost

__all__ = [
    "COMMAND_NAME",
    "OPEN_ACTIVITYWATCH",
    "CheckOutcome",
    "CheckRun",
    "Host",
    "HostError",
    "JobBusy",
    "JobState",
    "LiveHost",
]
