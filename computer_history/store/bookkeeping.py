"""Per-source ingest cursors.

Each setter is a single statement, so it is atomic on its own and also joins
an enclosing transaction() when called inside one.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from computer_history.store.timefmt import utc_iso


def get_cursor(conn: sqlite3.Connection, source: str) -> str | None:
    """The source's ingestion frontier, or None if never set.

    Returned as the stored UTC string; convert with to_utc() for time math.
    """
    row = conn.execute(
        "SELECT last_seen FROM ingest_cursors WHERE source = ?", (source,)
    ).fetchone()
    return None if row is None else row[0]


def set_cursor(conn: sqlite3.Connection, source: str, last_seen: datetime | str) -> None:
    """Set the frontier. It may move backwards; re-ingesting is harmless.

    When the cursor covers a batch of writes, pass it to insert_observations
    instead, so the two commit together.
    """
    conn.execute(
        "INSERT INTO ingest_cursors (source, last_seen) VALUES (?, ?) "
        "ON CONFLICT (source) DO UPDATE SET last_seen = excluded.last_seen",
        (source, utc_iso(last_seen)),
    )


def init_cursor(conn: sqlite3.Connection, source: str, last_seen: datetime | str) -> bool:
    """Set the frontier only if the source has none yet; True if this call set it.

    Whoever sets it first wins, so a cursor written concurrently (say by a
    running ingest --watch) is never overwritten. Used by backfill.
    """
    cur = conn.execute(
        "INSERT INTO ingest_cursors (source, last_seen) VALUES (?, ?) "
        "ON CONFLICT (source) DO NOTHING",
        (source, utc_iso(last_seen)),
    )
    return cur.rowcount == 1
