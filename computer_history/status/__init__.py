"""What `status` shows, as one value the CLI only formats.

report.py    read the database, the spool, ActivityWatch, the backups and the stable install,
             and judge the capture agent, ActivityWatch and the backend through the
             watchdog's assessment, writing nothing
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
