"""The capture spool adapter: the capture agent's window text and screenshot records.

    spool folder (paths.py: --spool-path, $COMPUTER_HISTORY_SPOOL, or beside the database)
          |
      spool.py       finished *.jsonl files oldest first (never open.part or agent.lock),
          |          read with what tells the file apart, removed once stored, or set
          |          aside into unreadable/
      record.py      one line -> a checked record of format v1 (InvalidRecord otherwise);
          |          the kinds each stream takes
          |
      adapter.py     CaptureSpool, two streams over the same files: ax-text (captures,
                     exclusions, pauses, resumes) and screenshot. Each pull reads one file
                     for one stream, its position that stream's latest capture time; the
                     after-commit step removes the file, or sets it aside if any line was
                     unusable, only once both streams stored that same file; more while
                     the stream's listed files remain
                     normalize.py: its projectors, stored record -> signal: app, title
                     and capped text (window text, or recognized text for screenshot),
                     the rest in extras

    For status: backlog.py   what waits in the spool and its newest record, changing nothing
                stored.py    the stored records' kinds, apps and flags, the newest, the
                             day's counts
                coverage.py  records judged against attended time: stretches no record
                             explains within the heartbeat tolerance, and liveness
                agreement.py each capture's app judged against the app aw-window shows
                             in front, within its polling tolerance
                screenshots.py
                             the stored screenshot records: the last kept, counts by
                             status, kept image bytes, and since when the newest say
                             no-permission

Re-reading a file after a crash between commit and removal stores nothing twice.
"""

from computer_history.sources.capture_spool.adapter import CaptureSpool
from computer_history.sources.capture_spool.agreement import (
    APP_TOLERANCE,
    AppAgreement,
    app_agreement,
)
from computer_history.sources.capture_spool.backlog import SpoolBacklog, spool_backlog
from computer_history.sources.capture_spool.coverage import (
    AGENT_ALIVE_WITHIN,
    CAPTURE_TOLERANCE,
    HEARTBEAT_SECONDS,
    Coverage,
    capture_coverage,
    liveness,
)
from computer_history.sources.capture_spool.normalize import (
    MAX_RECOGNIZED_TEXT_LENGTH,
    MAX_WINDOW_TEXT_LENGTH,
)
from computer_history.sources.capture_spool.paths import SPOOL_ENV_VAR, resolve_spool_path
from computer_history.sources.capture_spool.record import (
    CAPTURE_KIND,
    PAUSED_KIND,
    SCREENSHOT_KIND,
    SCREENSHOT_SOURCE,
    SPOOL_STREAMS,
    SPOOL_VERSION,
    WINDOW_TEXT_SOURCE,
    InvalidRecord,
    parse_record,
)
from computer_history.sources.capture_spool.screenshots import (
    KeptScreenshot,
    ScreenshotHealth,
    ScreenshotTally,
    screenshot_health,
)
from computer_history.sources.capture_spool.spool import (
    UNREADABLE_FOLDER,
    SpoolError,
    finished_files,
)
from computer_history.sources.capture_spool.stored import (
    DayCounts,
    StoredRecord,
    day_counts,
    newest_stored,
    stored_records,
)

__all__ = [
    "AGENT_ALIVE_WITHIN",
    "APP_TOLERANCE",
    "WINDOW_TEXT_SOURCE",
    "CAPTURE_KIND",
    "CAPTURE_TOLERANCE",
    "HEARTBEAT_SECONDS",
    "MAX_WINDOW_TEXT_LENGTH",
    "MAX_RECOGNIZED_TEXT_LENGTH",
    "PAUSED_KIND",
    "SCREENSHOT_KIND",
    "SCREENSHOT_SOURCE",
    "ScreenshotHealth",
    "ScreenshotTally",
    "SPOOL_ENV_VAR",
    "SPOOL_STREAMS",
    "SPOOL_VERSION",
    "UNREADABLE_FOLDER",
    "AppAgreement",
    "CaptureSpool",
    "Coverage",
    "DayCounts",
    "InvalidRecord",
    "KeptScreenshot",
    "SpoolBacklog",
    "SpoolError",
    "StoredRecord",
    "app_agreement",
    "capture_coverage",
    "day_counts",
    "finished_files",
    "liveness",
    "newest_stored",
    "parse_record",
    "resolve_spool_path",
    "screenshot_health",
    "spool_backlog",
    "stored_records",
]
