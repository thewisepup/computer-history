"""Where the SQLite database lives."""

from __future__ import annotations

import os
from pathlib import Path

DB_ENV_VAR = "COMPUTER_HISTORY_DB"


def default_db_path() -> Path:
    """The default database location in Application Support."""
    return Path.home() / "Library" / "Application Support" / "ComputerHistory" / "history.db"


def resolve_db_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Pick the database path: the --db-path value, then $COMPUTER_HISTORY_DB, then the default.

    Empty values count as unset, and ~ is expanded.
    """
    for candidate in (explicit, os.environ.get(DB_ENV_VAR)):
        if candidate:
            return Path(candidate).expanduser()
    return default_db_path()
