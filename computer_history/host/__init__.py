"""The host adapter: the one seam to macOS and the network.

    contract.py   Host (the Protocol), its answers (CheckRun, GitState, JobState,
                  BackendBuild, SpoolReads), HostError
                  JobBusy (launchd not done with a job yet) and
                  AgentNotUnregistered (the agent at the fixed path left as it
                  was), the command
                  that opens ActivityWatch, and how often a lasting problem may
                  notify again
        |
    live.py       LiveHost: launchctl in the login session, GitHub's public API
                  for check runs on main and the agent's source tree, git for a
                  checkout's state, uv for building a stable version, the agent's
                  toolchain check, build from a fresh export and install over its
                  fixed path, pgrep and open for ActivityWatch, osascript for
                  notifications under the one title, off when
                  $COMPUTER_HISTORY_NOTIFY is 0

Commands build a LiveHost and pass it down; tests pass a fake that records calls.
"""

from computer_history.host.contract import (
    ALERT_REPEAT,
    COMMAND_NAME,
    OPEN_ACTIVITYWATCH,
    SPOOL_READS_FLAG,
    AgentNotUnregistered,
    BackendBuild,
    CheckOutcome,
    CheckRun,
    GitState,
    Host,
    HostError,
    JobBusy,
    JobState,
    SpoolReads,
)
from computer_history.host.live import NOTIFY_ENV_VAR, LiveHost

__all__ = [
    "ALERT_REPEAT",
    "COMMAND_NAME",
    "NOTIFY_ENV_VAR",
    "OPEN_ACTIVITYWATCH",
    "SPOOL_READS_FLAG",
    "AgentNotUnregistered",
    "BackendBuild",
    "CheckOutcome",
    "CheckRun",
    "GitState",
    "Host",
    "HostError",
    "JobBusy",
    "JobState",
    "LiveHost",
    "SpoolReads",
]
