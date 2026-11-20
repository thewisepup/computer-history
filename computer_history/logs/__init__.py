"""Logging for every command: set up once by the CLI, read back by `computer-history logs`.

    config.py      one setup per run: the run id and command on every record, text
         |         to stderr, JSON lines to a rotating file in the log folder
    formatters.py  a record as one JSON line or one text line, control characters escaped
         |
    query.py       the JSON lines read back across the rotated files, filtered
    notify.py      a macOS notification, or none when they are turned off
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
from computer_history.logs.formatters import JsonFormatter, TextFormatter, escape, text_line
from computer_history.logs.notify import NOTIFY_ENV_VAR, desktop_notifier, post_notification
from computer_history.logs.query import LEVELS, log_files, read_records

__all__ = [
    "LEVEL_NAMES",
    "LEVELS",
    "LOG_BACKUPS",
    "LOG_DIR_ENV_VAR",
    "LOG_FILE_NAME",
    "LOG_LEVEL_ENV_VAR",
    "MAX_LOG_BYTES",
    "NOTIFY_ENV_VAR",
    "PACKAGE_LOGGER",
    "JsonFormatter",
    "TextFormatter",
    "configure",
    "default_log_dir",
    "desktop_notifier",
    "escape",
    "log_files",
    "post_notification",
    "read_records",
    "reset",
    "resolve_level",
    "resolve_log_dir",
    "text_line",
]
