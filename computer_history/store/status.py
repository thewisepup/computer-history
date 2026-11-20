from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from computer_history.store.timefmt import to_utc, utc_iso

STATUS_WINDOW = timedelta(hours=24)
MIN_GAP_SECONDS = 300


class SourceSummary(NamedTuple):
    source: str
    observation_count: int
    earliest_started_at: datetime | None
    latest_ended_at: datetime | None
    settled_until: datetime | None
    advanced_at: datetime | None


class Gap(NamedTuple):
    start: datetime
    end: datetime

    @property
    def seconds(self) -> float:
        return (self.end - self.start).total_seconds()


_SOURCE_SUMMARY = """
WITH obs AS (
  SELECT source, COUNT(*) AS n, MIN(started_at) AS earliest, MAX(ended_at) AS latest
  FROM observations
  GROUP BY source
)
SELECT s.source, COALESCE(obs.n, 0), obs.earliest, obs.latest, p.settled_until, p.advanced_at
FROM (SELECT source FROM obs UNION SELECT source FROM ingest_progress) AS s
LEFT JOIN obs USING (source)
LEFT JOIN ingest_progress AS p USING (source)
ORDER BY s.source
"""


def source_summary(conn: sqlite3.Connection) -> list[SourceSummary]:
    """One row per source that has observations or ingest progress, sorted by source."""
    return [
        SourceSummary(source, count, *(_maybe_utc(value) for value in times))
        for source, count, *times in conn.execute(_SOURCE_SUMMARY)
    ]


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Row count of every table in the schema."""
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {name: conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] for name in names}


def recent_span(
    summary: SourceSummary, window: timedelta = STATUS_WINDOW
) -> tuple[datetime, datetime] | None:
    """The window status checks: up to the source's settled time, else its latest end.

    It starts no earlier than the source's first observation, and is None without one.
    """
    end = summary.settled_until or summary.latest_ended_at
    first = summary.earliest_started_at
    if end is None or first is None:
        return None
    return max(end - window, first), end


def find_gaps(
    conn: sqlite3.Connection,
    source: str,
    start: datetime | str,
    end: datetime | str,
    min_gap_seconds: float = 0,
) -> list[Gap]:
    """The spans of the range that no observation from the source covers.

    A gap is missing data, not idle time.
    """
    start_text, end_text = utc_iso(start), utc_iso(end)
    if end_text <= start_text:
        raise ValueError(f"find_gaps range is empty: [{start_text}, {end_text})")
    rows = conn.execute(
        "SELECT started_at, ended_at FROM observations "
        "WHERE source = ? AND started_at < ? AND ended_at > ? AND ended_at > started_at "
        "ORDER BY started_at",
        (source, end_text, start_text),
    )
    gaps: list[tuple[str, str]] = []
    covered_until = start_text
    for started, ended in rows:
        if started > covered_until:
            gaps.append((covered_until, started))
        covered_until = max(covered_until, ended)
    if covered_until < end_text:
        gaps.append((covered_until, end_text))
    result = [Gap(to_utc(a), to_utc(b)) for a, b in gaps]
    return [gap for gap in result if gap.seconds >= min_gap_seconds]


_VALUE = "CASE WHEN json_valid(payload) THEN json_extract(payload, ?) END"


class PayloadValues(NamedTuple):
    started_at: datetime
    ended_at: datetime
    values: tuple[Any, ...]
    source_id: str = ""


def payload_values(
    conn: sqlite3.Connection,
    source: str,
    start: datetime | str,
    end: datetime | str,
    paths: Sequence[str],
) -> list[PayloadValues]:
    """The source's observations that touch the range, oldest first, with their source ids.

    The values are those at the given JSON paths of each payload, in order.
    """
    if not paths:
        raise ValueError("payload_values needs at least one JSON path")
    columns = ", ".join(_VALUE for _ in paths)
    rows = conn.execute(
        f"SELECT started_at, ended_at, source_id, {columns} FROM observations "
        "WHERE source = ? AND started_at <= ? AND ended_at >= ? ORDER BY started_at, id",
        (*paths, source, utc_iso(end), utc_iso(start)),
    )
    return [
        PayloadValues(to_utc(a), to_utc(b), tuple(values), source_id)
        for a, b, source_id, *values in rows
    ]


def latest_payload_value(
    conn: sqlite3.Connection,
    source: str,
    path: str,
    *,
    until: datetime | str,
    matching: Any = None,
) -> tuple[datetime, Any] | None:
    """The start and payload value at the path of the source's newest observation up to a time.

    Given a value to match, only observations whose payload has that value there count.
    """
    match = "" if matching is None else f" AND {_VALUE} = ?"
    row = conn.execute(
        f"SELECT started_at, {_VALUE} FROM observations WHERE source = ? AND started_at <= ?"
        f"{match} ORDER BY started_at DESC, id DESC LIMIT 1",
        (path, source, utc_iso(until), *(() if matching is None else (path, matching))),
    ).fetchone()
    return None if row is None else (to_utc(row[0]), row[1])


def _maybe_utc(value: str | None) -> datetime | None:
    return None if value is None else to_utc(value)
