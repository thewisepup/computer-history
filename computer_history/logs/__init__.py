"""Logging for every command: set up once by the CLI, read back by `computer-history logs`.

config.py      one setup per run: the run id and command on every record, text
     |         to stderr, JSON lines to the log folder
rotation.py    the JSON log file, size-rotated, shared by every running process
formatters.py  a record as one JSON line or one text line, control characters escaped
     |
query.py       the JSON lines read back across the rotated files, filtered
units.py       what every unit of work's records share: outcomes, progress cadence
"""

from computer_history.logs.config import (
    LEVEL_NAMES,
    LOG_BACKUPS,
    LOG_DIR_ENV_VAR,
    LOG_FILE_NAME,
    LOG_LEVEL_ENV_VAR,
    MAX_LOG_BYTES,
    PACKAGE_LOGGER,
    configure,
    default_log_dir,
    reset,
    resolve_level,
    resolve_log_dir,
)
from computer_history.logs.formatters import (
    SHOWN_FIELD,
    JsonFormatter,
    TextFormatter,
    escape,
    text_line,
)
from computer_history.logs.query import LEVELS, log_files, read_records
from computer_history.logs.rotation import SharedRotatingFileHandler
from computer_history.logs.units import PROGRESS_RECORDS, Outcome, progress_step

__all__ = [
    "LEVELS",
    "LEVEL_NAMES",
    "LOG_BACKUPS",
    "LOG_DIR_ENV_VAR",
    "LOG_FILE_NAME",
    "LOG_LEVEL_ENV_VAR",
    "MAX_LOG_BYTES",
    "PACKAGE_LOGGER",
    "PROGRESS_RECORDS",
    "SHOWN_FIELD",
    "JsonFormatter",
    "Outcome",
    "SharedRotatingFileHandler",
    "TextFormatter",
    "configure",
    "default_log_dir",
    "escape",
    "log_files",
    "progress_step",
    "read_records",
    "reset",
    "resolve_level",
    "resolve_log_dir",
    "text_line",
]
