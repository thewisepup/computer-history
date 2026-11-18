"""Helpers every command uses."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from computer_history.store import connect


def open_store(db_path: Path) -> sqlite3.Connection | None:
    """Open (and migrate if needed) the database, or None after printing why it failed."""
    try:
        return connect(db_path)
    except sqlite3.OperationalError as exc:
        print(f"cannot open {db_path}: {exc}", file=sys.stderr)
        print(db_busy_hint(db_path), file=sys.stderr)
        return None


def db_busy_hint(db_path: Path) -> str:
    return f"Is another process writing to {db_path}? Try again shortly."
