"""Per-source ingest cursors."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from computer_history.store.timefmt import utc_iso


def get_cursor(conn: sqlite3.Connection, source: str) -> str | None:
    """The source's cursor, or None if never set."""
    row = conn.execute(
        "SELECT last_seen FROM ingest_cursors WHERE source = ?", (source,)
    ).fetchone()
    return None if row is None else row[0]


def set_cursor(conn: sqlite3.Connection, source: str, last_seen: datetime | str) -> None:
    """Set the source's cursor."""
    conn.execute(
        "INSERT INTO ingest_cursors (source, last_seen) VALUES (?, ?) "
        "ON CONFLICT (source) DO UPDATE SET last_seen = excluded.last_seen",
        (source, utc_iso(last_seen)),
    )


def init_cursor(conn: sqlite3.Connection, source: str, last_seen: datetime | str) -> bool:
    """Set the cursor only if the source has none yet. True if this call set it."""
    cur = conn.execute(
        "INSERT INTO ingest_cursors (source, last_seen) VALUES (?, ?) "
        "ON CONFLICT (source) DO NOTHING",
        (source, utc_iso(last_seen)),
    )
    return cur.rowcount == 1
