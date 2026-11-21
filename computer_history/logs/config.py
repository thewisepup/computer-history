from __future__ import annotations

import contextvars
import logging
import logging.handlers
import os
import sys
import uuid
from pathlib import Path

from computer_history.logs.formatters import JsonFormatter, TextFormatter

LOG_DIR_ENV_VAR = "COMPUTER_HISTORY_LOG_DIR"
LOG_LEVEL_ENV_VAR = "COMPUTER_HISTORY_LOG_LEVEL"
LOG_FILE_NAME = "computer-history.jsonl"
MAX_LOG_BYTES = 10_000_000
LOG_BACKUPS = 5
PACKAGE_LOGGER = "computer_history"
LEVEL_NAMES = ("DEBUG", "INFO", "WARNING", "ERROR")

_run_id = contextvars.ContextVar("run_id", default="-")
_command = contextvars.ContextVar("command", default="-")
log = logging.getLogger(__name__)


def default_log_dir() -> Path:
    """The default log folder in the user's Library/Logs."""
    return Path.home() / "Library" / "Logs" / "computer-history"


def resolve_log_dir() -> Path:
    """Pick the log folder: $COMPUTER_HISTORY_LOG_DIR, else the default, with ~ expanded."""
    value = os.environ.get(LOG_DIR_ENV_VAR)
    return Path(value).expanduser() if value else default_log_dir()


def resolve_level(explicit: str | None) -> int | None:
    """The --log-level value, then $COMPUTER_HISTORY_LOG_LEVEL, or None when neither is set."""
    for name in (explicit, os.environ.get(LOG_LEVEL_ENV_VAR)):
        if name:
            if name.upper() not in LEVEL_NAMES:
                raise ValueError(f"unknown log level {name!r} (one of {', '.join(LEVEL_NAMES)})")
            return logging.getLevelNamesMapping()[name.upper()]
    return None


class _Context(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run = _run_id.get()
        record.cmd = _command.get()
        return True


def configure(command: str, *, level: int, stderr_level: int, log_dir: Path) -> Path | None:
    """Send the package's records as text to stderr and as JSON lines to the log folder.

    Every record carries a new run id and the command; returns the log file, or None if unusable.
    """
    reset()
    _command.set(command)
    _run_id.set(uuid.uuid4().hex[:8])
    package = logging.getLogger(PACKAGE_LOGGER)
    package.setLevel(min(level, stderr_level))
    context = _Context()
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setLevel(stderr_level)
    stderr.setFormatter(TextFormatter(tracebacks=stderr_level <= logging.DEBUG))
    stderr.addFilter(context)
    package.addHandler(stderr)
    path = log_dir / LOG_FILE_NAME
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file = logging.handlers.RotatingFileHandler(
            path, maxBytes=MAX_LOG_BYTES, backupCount=LOG_BACKUPS, encoding="utf-8", delay=True
        )
    except OSError as exc:
        log.warning("log file unavailable", extra={"path": str(path), "error": str(exc)})
        return None
    file.setLevel(level)
    file.setFormatter(JsonFormatter())
    file.addFilter(context)
    package.addHandler(file)
    return path


def reset() -> None:
    """Remove and close the package's handlers and clear its level."""
    package = logging.getLogger(PACKAGE_LOGGER)
    for handler in list(package.handlers):
        package.removeHandler(handler)
        handler.close()
    package.setLevel(logging.NOTSET)
