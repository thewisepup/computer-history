"""Where the SQLite database lives."""

from __future__ import annotations

import os
from pathlib import Path

DB_ENV_VAR = "COMPUTER_HISTORY_DB"


def default_db_path() -> Path:
    """``~/Library/Application Support/ComputerHistory/history.db`` (read at call time)."""
    return Path.home() / "Library" / "Application Support" / "ComputerHistory" / "history.db"


def resolve_db_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Pick the database path: ``--db-path`` value > ``$COMPUTER_HISTORY_DB`` > default.

    Empty strings count as unset, so ``COMPUTER_HISTORY_DB=`` falls through to the
    default. ``~`` is expanded in explicit and environment values.
    """
    for candidate in (explicit, os.environ.get(DB_ENV_VAR)):
        if candidate:
            return Path(candidate).expanduser()
    return default_db_path()
