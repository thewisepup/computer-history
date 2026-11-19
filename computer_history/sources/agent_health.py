from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from computer_history.sources.activitywatch import (
    AfkSpan,
    AWApi,
    newest_afk_spans,
    stored_afk_spans,
)
from computer_history.sources.ax_text import (
    AX_TEXT_SOURCE,
    CAPTURE_KIND,
    CAPTURE_TOLERANCE,
    PAUSED_KIND,
    Coverage,
    DayCounts,
    SpoolBacklog,
    SpoolError,
    capture_coverage,
    day_counts,
    liveness,
    newest_stored,
    spool_backlog,
    stored_records,
)
from computer_history.sources.contract import SourceUnavailable
from computer_history.store import SourceSummary, to_utc

__all__ = ["CaptureHealth", "capture_health"]


@dataclass(frozen=True)
class CaptureHealth:
    """What status reports about the capture agent. It has not reported until a record is stored."""

    reported: bool
    spool: SpoolBacklog | None
    spool_error: str | None
    last_capture: datetime | None = None
    last_record: datetime | None = None
    alive: str = "unknown"
    paused_since: datetime | None = None
    today: DayCounts = DayCounts()
    coverage: Coverage | None = None


def capture_health(
    conn: sqlite3.Connection,
    summaries: Iterable[SourceSummary],
    spool_folder: Path,
    client: AWApi | None,
    *,
    now: datetime,
    window: timedelta,
    min_gap_seconds: float = 0,
    day_start: datetime | None = None,
) -> CaptureHealth:
    """Report on the agent from its stored records, its spool folder and aw-afk, as of now.

    With a client, the newest AFK events in ActivityWatch count too, even those not stored yet.
    """
    now = to_utc(now)
    try:
        spool, spool_error = spool_backlog(spool_folder), None
    except SpoolError as exc:
        spool, spool_error = None, str(exc)
    summary = next((s for s in summaries if s.source == AX_TEXT_SOURCE), None)
    stored = newest_stored(conn, until=now)
    if summary is None or summary.earliest_started_at is None or stored is None:
        return CaptureHealth(False, spool, spool_error)

    unstored = None if spool is None else spool.newest
    newest = unstored if unstored is not None and unstored[0] > stored[0] else stored
    end = stored[0] if spool is None or spool.unstored else now
    start = max(end - window, summary.earliest_started_at)
    if day_start is None:
        day_start = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    day_start = to_utc(day_start)
    read_from = min(start - CAPTURE_TOLERANCE, day_start)

    records = stored_records(conn, read_from, now)
    before = newest_stored(conn, until=read_from)
    paused = newest[1] == PAUSED_KIND
    afk = _afk_spans(conn, client, min(read_from, newest[0]), now)
    active = [(s.start, s.end) for s in afk if not s.afk]
    coverage = None
    if start < end:
        coverage = capture_coverage(
            records,
            active=active,
            known=[(s.start, s.end) for s in afk],
            start=start,
            end=end,
            paused_at_start=before is not None and before[1] == PAUSED_KIND,
            min_gap_seconds=min_gap_seconds,
        )
    return CaptureHealth(
        reported=True,
        spool=spool,
        spool_error=spool_error,
        last_capture=_last_capture(conn, now, unstored),
        last_record=newest[0],
        alive=liveness(newest[0], now=now, paused=paused, active=active),
        paused_since=newest[0] if paused else None,
        today=day_counts(records, day_start),
        coverage=coverage,
    )


def _last_capture(
    conn: sqlite3.Connection, now: datetime, unstored: tuple[datetime, str] | None
) -> datetime | None:
    stored = newest_stored(conn, until=now, kind=CAPTURE_KIND)
    times = [] if stored is None else [stored[0]]
    if unstored is not None and unstored[1] == CAPTURE_KIND:
        times.append(unstored[0])
    return max(times, default=None)


def _afk_spans(
    conn: sqlite3.Connection, client: AWApi | None, start: datetime, end: datetime
) -> list[AfkSpan]:
    spans = stored_afk_spans(conn, start, end)
    if client is not None:
        try:
            spans.extend(newest_afk_spans(client))
        except SourceUnavailable:
            pass
    return spans
