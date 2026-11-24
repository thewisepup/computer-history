"""The capture spool adapter: the capture agent's window text and screenshot records.

    spool folder (paths.py: --spool-path, $COMPUTER_HISTORY_SPOOL, or beside the database,
          |       where the agent's config file sits too)
          |
      spool.py       finished *.jsonl files oldest first (never open.part or agent.lock),
          |          read with what tells the file apart, removed once stored, or set
          |          aside into unreadable/
      record.py      one line -> a checked record of format v1 (InvalidRecord otherwise);
          |          the kinds each stream takes, and the Mac's sleep and wake moments
          |
      adapter.py     CaptureSpool, two streams over the same files: ax-text (captures,
                     exclusions, pauses, resumes, sleeps, wakes) and screenshot. Each pull
                     reads one file for one stream, its position that stream's latest
                     capture time; the after-commit step removes the file, or sets it
                     aside if any line was unusable, only once both streams stored that
                     same file; more while the stream's listed files remain. Each file's
                     state moves through FILE_STATES: listed, stored or unreadable by
                     some then all streams, then removed, kept for the hold, or stuck
                     normalize.py: its projectors, stored record -> signal: app, title
                     and capped text (window text, or recognized text for screenshot),
                     the rest in extras; a sleep or wake's kind alone, in extras

    For status: backlog.py   what waits in the spool and its newest record, changing nothing
                window_text.py
                             the stored window text records' kinds, apps and flags, the newest,
                             the day's counts
                coverage.py  records judged against attended time: stretches no record
                             explains within the heartbeat tolerance and no pause or
                             sleep explains, liveness, and the attended time between two times
                agreement.py each capture's app judged against the app aw-window shows
                             in front, within its polling tolerance
                screenshots.py
                             the stored screenshot records: the last kept, counts by
                             status, kept image bytes, and since when the newest say
                             no-permission, current while the newest is recent

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
    Liveness,
    Span,
    attended_time,
    capture_coverage,
    liveness,
)
from computer_history.sources.capture_spool.normalize import (
    MAX_RECOGNIZED_TEXT_LENGTH,
    MAX_WINDOW_TEXT_LENGTH,
)
from computer_history.sources.capture_spool.paths import (
    SPOOL_ENV_VAR,
    agent_config_path,
    configured_spool_path,
    default_spool_path,
    resolve_spool_path,
)
from computer_history.sources.capture_spool.record import (
    CAPTURE_KIND,
    DUPLICATE_STATUS,
    EXCLUDED_KIND,
    KEPT_STATUS,
    MOMENT_KINDS,
    PAUSED_KIND,
    RECORD_KINDS,
    RESUMED_KIND,
    SCREENSHOT_KIND,
    SCREENSHOT_RECORD_FIELDS,
    SCREENSHOT_SOURCE,
    SLEPT_KIND,
    SPOOL_STREAMS,
    SPOOL_VERSION,
    WINDOW_TEXT_RECORD_FIELDS,
    WINDOW_TEXT_SOURCE,
    WOKE_KIND,
    InvalidRecord,
    parse_record,
)
from computer_history.sources.capture_spool.screenshots import (
    KeptScreenshot,
    MissingPermission,
    ScreenshotHealth,
    ScreenshotTally,
    screenshot_health,
)
from computer_history.sources.capture_spool.spool import (
    UNREADABLE_FOLDER,
    SpoolError,
    finished_files,
)
from computer_history.sources.capture_spool.window_text import (
    DayCounts,
    StoredRecord,
    day_counts,
    newest_stored,
    stored_records,
)

__all__ = [
    "AGENT_ALIVE_WITHIN",
    "APP_TOLERANCE",
    "CAPTURE_KIND",
    "CAPTURE_TOLERANCE",
    "DUPLICATE_STATUS",
    "EXCLUDED_KIND",
    "HEARTBEAT_SECONDS",
    "KEPT_STATUS",
    "MAX_RECOGNIZED_TEXT_LENGTH",
    "MAX_WINDOW_TEXT_LENGTH",
    "MOMENT_KINDS",
    "PAUSED_KIND",
    "RECORD_KINDS",
    "RESUMED_KIND",
    "SCREENSHOT_KIND",
    "SCREENSHOT_RECORD_FIELDS",
    "SCREENSHOT_SOURCE",
    "SLEPT_KIND",
    "SPOOL_ENV_VAR",
    "SPOOL_STREAMS",
    "SPOOL_VERSION",
    "UNREADABLE_FOLDER",
    "WINDOW_TEXT_RECORD_FIELDS",
    "WINDOW_TEXT_SOURCE",
    "WOKE_KIND",
    "AppAgreement",
    "CaptureSpool",
    "Coverage",
    "DayCounts",
    "InvalidRecord",
    "KeptScreenshot",
    "Liveness",
    "MissingPermission",
    "ScreenshotHealth",
    "ScreenshotTally",
    "Span",
    "SpoolBacklog",
    "SpoolError",
    "StoredRecord",
    "agent_config_path",
    "app_agreement",
    "attended_time",
    "capture_coverage",
    "configured_spool_path",
    "day_counts",
    "default_spool_path",
    "finished_files",
    "liveness",
    "newest_stored",
    "parse_record",
    "resolve_spool_path",
    "screenshot_health",
    "spool_backlog",
    "stored_records",
]
