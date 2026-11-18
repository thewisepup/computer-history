"""Ingest cursors (DESIGN.md §3.5).

Each setter is a single statement, so it is atomic on its own and also joins an
enclosing ``transaction()`` when called inside one.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from computer_history.store.timefmt import utc_iso


def get_cursor(conn: sqlite3.Connection, source: str) -> str | None:
    """The source's ingestion frontier, or None if never set.

    Returns the canonical UTC *string* as stored — the form adapters pass back
    to source APIs. For lag math, convert with ``to_utc()``; note that
    ``SourceSummary.cursor`` returns the same value as a ``datetime``.
    """
    row = conn.execute(
        "SELECT last_seen FROM ingest_cursors WHERE source = ?", (source,)
    ).fetchone()
    return None if row is None else row[0]


def set_cursor(conn: sqlite3.Connection, source: str, last_seen: datetime | str) -> None:
    """Upsert the frontier. It may move backwards; re-ingesting is idempotent.

    Prefer ``insert_observations(..., advance_cursor=...)`` when the cursor covers
    a batch, so the two commit together.
    """
    conn.execute(
        "INSERT INTO ingest_cursors (source, last_seen) VALUES (?, ?) "
        "ON CONFLICT (source) DO UPDATE SET last_seen = excluded.last_seen",
        (source, utc_iso(last_seen)),
    )


def init_cursor(conn: sqlite3.Connection, source: str, last_seen: datetime | str) -> bool:
    """Set the frontier only if the source has none yet; True if this call set it.

    One statement, so a cursor written concurrently (e.g. by ``ingest --watch``)
    is never overwritten: whoever sets it first wins. ``backfill`` uses this.
    """
    cur = conn.execute(
        "INSERT INTO ingest_cursors (source, last_seen) VALUES (?, ?) "
        "ON CONFLICT (source) DO NOTHING",
        (source, utc_iso(last_seen)),
    )
    return cur.rowcount == 1
