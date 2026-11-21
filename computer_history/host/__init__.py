"""The host adapter: the one seam to macOS and the network.

    contract.py   Host (the Protocol), its answers (CheckRun, JobState) and HostError
        |
    live.py       LiveHost: launchctl in the login session, GitHub's public API
                  for check runs on main, and uv for building a stable version

Commands build a LiveHost and pass it down; tests pass a fake that records calls.
"""

from computer_history.host.contract import (
    COMMAND_NAME,
    CheckOutcome,
    CheckRun,
    Host,
    HostError,
    JobState,
)
from computer_history.host.live import LiveHost

__all__ = [
    "COMMAND_NAME",
    "CheckOutcome",
    "CheckRun",
    "Host",
    "HostError",
    "JobState",
    "LiveHost",
]
