"""The capture spool adapter: the capture agent's AX-text captures, read from the spool.

    spool folder (paths.py: --spool-path, $COMPUTER_HISTORY_SPOOL, or beside the database)
          |
      spool.py       finished *.jsonl files oldest first (never open.part or agent.lock),
          |          read, removed once stored, or set aside into unreadable/
      record.py      one line -> a checked record of format v1 (InvalidRecord otherwise)
          |
      adapter.py     CaptureSpool: one file per pull, its position the latest capture time,
                     its after-commit step removing the file, or setting it aside if any
                     line was unusable; more while listed files remain
                     normalize.py: its projector, stored record -> signal
                     (app, title, capped text, the rest in extras)

    For status: backlog.py   what waits in the spool and its newest record, changing nothing
                stored.py    the stored records' kinds and flags, the newest, the day's counts
                coverage.py  records judged against attended time: stretches no record
                             explains within the heartbeat tolerance, and liveness

Re-reading a file after a crash between commit and removal stores nothing twice.
"""

from computer_history.sources.ax_text.adapter import CaptureSpool
from computer_history.sources.ax_text.backlog import SpoolBacklog, spool_backlog
from computer_history.sources.ax_text.coverage import (
    AGENT_ALIVE_WITHIN,
    CAPTURE_TOLERANCE,
    HEARTBEAT_SECONDS,
    Coverage,
    capture_coverage,
    liveness,
)
from computer_history.sources.ax_text.normalize import (
    AX_TEXT_SOURCE,
    MAX_AX_TEXT_LENGTH,
    project_capture,
)
from computer_history.sources.ax_text.paths import SPOOL_ENV_VAR, resolve_spool_path
from computer_history.sources.ax_text.record import (
    SPOOL_VERSION,
    InvalidRecord,
    SpoolRecord,
    parse_record,
)
from computer_history.sources.ax_text.spool import UNREADABLE_FOLDER, SpoolError, finished_files
from computer_history.sources.ax_text.stored import (
    DayCounts,
    StoredRecord,
    day_counts,
    newest_stored,
    stored_records,
)

__all__ = [
    "AGENT_ALIVE_WITHIN",
    "AX_TEXT_SOURCE",
    "CAPTURE_TOLERANCE",
    "HEARTBEAT_SECONDS",
    "MAX_AX_TEXT_LENGTH",
    "SPOOL_ENV_VAR",
    "SPOOL_VERSION",
    "UNREADABLE_FOLDER",
    "CaptureSpool",
    "Coverage",
    "DayCounts",
    "InvalidRecord",
    "SpoolBacklog",
    "SpoolError",
    "SpoolRecord",
    "StoredRecord",
    "capture_coverage",
    "day_counts",
    "finished_files",
    "liveness",
    "newest_stored",
    "parse_record",
    "project_capture",
    "resolve_spool_path",
    "spool_backlog",
    "stored_records",
]
