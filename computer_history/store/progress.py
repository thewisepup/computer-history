"""Per-source ingest progress: how far each source has been read.

The store keeps a source's position exactly as the source wrote it.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from computer_history.store.timefmt import to_utc, utc_iso


@dataclass(frozen=True)
class Progress:
    """Where a source's ingest has reached, how far its data is complete, and when it last moved."""

    source: str
    position: str
    settled_until: datetime | None
    advanced_at: datetime


@dataclass(frozen=True)
class ProgressUpdate:
    """New progress for a source, written together with a batch of observations.

    With only_if_none it is written only if the source has no progress yet.
    """

    source: str
    position: str
    settled_until: datetime | str | None = None
    only_if_none: bool = False

    def __post_init__(self) -> None:
        if not self.source:
            raise ValueError("progress update has no source")
        if not isinstance(self.position, str) or not self.position:
            raise ValueError(f"progress update for {self.source!r} has no position")
        if self.settled_until is not None:
            to_utc(self.settled_until)


_ADVANCE = """
INSERT INTO ingest_progress (source, position, settled_until, advanced_at)
VALUES (?, ?, ?, ?)
ON CONFLICT (source) DO UPDATE SET
  position = excluded.position,
  settled_until = excluded.settled_until,
  advanced_at = excluded.advanced_at
WHERE position IS NOT excluded.position OR settled_until IS NOT excluded.settled_until
"""

_ONLY_IF_NONE = """
INSERT INTO ingest_progress (source, position, settled_until, advanced_at)
VALUES (?, ?, ?, ?)
ON CONFLICT (source) DO NOTHING
"""


def get_progress(conn: sqlite3.Connection, source: str) -> Progress | None:
    """The source's progress, or None if it has none yet."""
    row = conn.execute(
        "SELECT position, settled_until, advanced_at FROM ingest_progress WHERE source = ?",
        (source,),
    ).fetchone()
    if row is None:
        return None
    position, settled_until, advanced_at = row
    settled = None if settled_until is None else to_utc(settled_until)
    return Progress(source, position, settled, to_utc(advanced_at))


def write_with_batch(conn: sqlite3.Connection, update: ProgressUpdate, *, advanced_at: str) -> bool:
    """Write the update inside the batch transaction already open on the connection.

    Returns whether the progress changed, which it does not when the update repeats it.
    """
    if not conn.in_transaction:
        raise RuntimeError("ingest progress only moves inside a batch's transaction")
    settled = None if update.settled_until is None else utc_iso(update.settled_until)
    sql = _ONLY_IF_NONE if update.only_if_none else _ADVANCE
    result = conn.execute(sql, (update.source, update.position, settled, advanced_at))
    return result.rowcount == 1
