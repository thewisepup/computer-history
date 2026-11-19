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

Re-reading a file after a crash between commit and removal stores nothing twice.
"""

from computer_history.sources.ax_text.adapter import CaptureSpool
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

__all__ = [
    "AX_TEXT_SOURCE",
    "MAX_AX_TEXT_LENGTH",
    "SPOOL_ENV_VAR",
    "SPOOL_VERSION",
    "UNREADABLE_FOLDER",
    "CaptureSpool",
    "InvalidRecord",
    "SpoolError",
    "SpoolRecord",
    "finished_files",
    "parse_record",
    "project_capture",
    "resolve_spool_path",
]
