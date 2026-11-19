"""The agent's stored records, for status: their kinds and flags, the newest, the day's counts."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple

from computer_history.sources.ax_text.normalize import AX_TEXT_SOURCE
from computer_history.sources.ax_text.record import CAPTURE_KIND, EXCLUDED_KIND
from computer_history.store import latest_payload_value, payload_values

KIND_PATH = "$.kind"
FLAG_PATHS = ("$.text_cut_off", "$.timed_out")


class StoredRecord(NamedTuple):
    at: datetime
    kind: str | None
    cut_off: bool = False
    timed_out: bool = False


@dataclass(frozen=True)
class DayCounts:
    captures: int = 0
    excluded: int = 0
    cut_off: int = 0
    timed_out: int = 0


def stored_records(conn: sqlite3.Connection, start: datetime, end: datetime) -> list[StoredRecord]:
    """The stored records captured in the range, oldest first."""
    rows = payload_values(conn, AX_TEXT_SOURCE, start, end, (KIND_PATH, *FLAG_PATHS))
    return [
        StoredRecord(row.started_at, kind if isinstance(kind, str) else None, bool(cut), bool(out))
        for row in rows
        for kind, cut, out in [row.values]
    ]


def newest_stored(
    conn: sqlite3.Connection, *, until: datetime, kind: str | None = None
) -> tuple[datetime, str | None] | None:
    """The time and kind of the newest stored record up to a time, of a kind if given."""
    found = latest_payload_value(conn, AX_TEXT_SOURCE, KIND_PATH, until=until, matching=kind)
    if found is None:
        return None
    at, value = found
    return at, value if isinstance(value, str) else None


def day_counts(records: Iterable[StoredRecord], since: datetime) -> DayCounts:
    """Count the captures and excluded records from a time on, and captures cut off or timed out."""
    captures = excluded = cut_off = timed_out = 0
    for record in records:
        if record.at < since:
            continue
        if record.kind == EXCLUDED_KIND:
            excluded += 1
        elif record.kind == CAPTURE_KIND:
            captures += 1
            cut_off += record.cut_off
            timed_out += record.timed_out
    return DayCounts(captures, excluded, cut_off, timed_out)
