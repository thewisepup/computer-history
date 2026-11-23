"""What `status` shows, as one value the CLI only formats.

store, spool, ActivityWatch, ingest health,
watchdog state and thresholds
    |
    +--> watchdog's assess: the capture agent, ActivityWatch, the backend
    |        |
store (sources, gaps, capture health, screenshots, counts),
backups, stable install, LaunchAgents, stable watchdog state
    |        |
    v        v
report.py    builds StatusReport from both, writing nothing
    |
    v
the status command in cli/ prints it
"""

from computer_history.status.report import (
    CaptureGaps,
    InstallDetails,
    JudgedElsewhere,
    SavedWatchdog,
    StatusReport,
    StoreDetails,
    status_report,
)

__all__ = [
    "CaptureGaps",
    "InstallDetails",
    "JudgedElsewhere",
    "SavedWatchdog",
    "StatusReport",
    "StoreDetails",
    "status_report",
]
