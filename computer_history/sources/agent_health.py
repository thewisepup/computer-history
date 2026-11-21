from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from computer_history.sources.activitywatch import (
    AfkSpan,
    AppSpan,
    AWApi,
    newest_afk_spans,
    newest_app_spans,
    stored_afk_spans,
    stored_app_spans,
)
from computer_history.sources.capture_spool import (
    APP_TOLERANCE,
    CAPTURE_KIND,
    CAPTURE_TOLERANCE,
    PAUSED_KIND,
    SLEPT_KIND,
    WINDOW_TEXT_SOURCE,
    AppAgreement,
    Coverage,
    DayCounts,
    Liveness,
    Span,
    SpoolBacklog,
    SpoolError,
    StoredRecord,
    app_agreement,
    capture_coverage,
    day_counts,
    liveness,
    newest_stored,
    spool_backlog,
    stored_records,
)
from computer_history.sources.contract import SourceUnavailable
from computer_history.store import SourceSummary, to_utc

__all__ = [
    "CaptureHealth",
    "CaptureLiveness",
    "active_spans",
    "capture_health",
    "capture_liveness",
]


@dataclass(frozen=True)
class CaptureHealth:
    """What status reports about the capture agent. It has not reported until a record is stored."""

    reported: bool
    spool: SpoolBacklog | None
    spool_error: str | None
    last_capture: datetime | None = None
    last_record: datetime | None = None
    alive: Liveness = Liveness.UNKNOWN
    paused_since: datetime | None = None
    today: DayCounts = DayCounts()
    coverage: Coverage | None = None
    agreement: AppAgreement | None = None


def capture_health(
    conn: sqlite3.Connection,
    summaries: Iterable[SourceSummary],
    spool_folder: Path,
    client: AWApi | None,
    *,
    now: datetime,
    window: timedelta,
    hostname: str,
    day_start: datetime,
    min_gap_seconds: float = 0,
) -> CaptureHealth:
    """Report on the agent from its stored records, its spool, aw-afk and aw-window, as of now.

    Only this host's window buckets count, and with a client their newest events and AFK's do too.
    """
    now = to_utc(now)
    try:
        spool, spool_error = spool_backlog(spool_folder), None
    except SpoolError as exc:
        spool, spool_error = None, str(exc)
    summary = next((s for s in summaries if s.source == WINDOW_TEXT_SOURCE), None)
    stored = newest_stored(conn, until=now)
    if summary is None or summary.earliest_started_at is None or stored is None:
        return CaptureHealth(False, spool, spool_error)

    unstored = None if spool is None else spool.newest
    newest = unstored if unstored is not None and unstored[0] > stored[0] else stored
    end = stored[0] if spool is None or spool.unstored else now
    start = max(end - window, summary.earliest_started_at)
    day_start = to_utc(day_start)
    read_from = min(start - CAPTURE_TOLERANCE, day_start)

    records = stored_records(conn, read_from, now)
    before = newest_stored(conn, until=read_from)
    earlier = None if before is None else StoredRecord(*before)
    paused = newest[1] == PAUSED_KIND
    buckets = _buckets(client)
    afk_from = min(read_from, newest[0])
    if earlier is not None and earlier.kind == SLEPT_KIND:
        afk_from = min(afk_from, earlier.at)
    afk = _afk_spans(conn, client, buckets, afk_from, now)
    active = [(s.start, s.end) for s in afk if not s.afk]
    coverage = agreement = None
    if start < end:
        agreement = app_agreement(
            records,
            _app_spans(conn, client, buckets, start - APP_TOLERANCE, end + APP_TOLERANCE, hostname),
            start=start,
            end=end,
        )
        coverage = capture_coverage(
            records,
            active=active,
            known=[(s.start, s.end) for s in afk],
            start=start,
            end=end,
            before=earlier,
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
        agreement=agreement,
    )


def _last_capture(
    conn: sqlite3.Connection, now: datetime, unstored: tuple[datetime, str] | None
) -> datetime | None:
    stored = newest_stored(conn, until=now, kind=CAPTURE_KIND)
    times = [] if stored is None else [stored[0]]
    if unstored is not None and unstored[1] == CAPTURE_KIND:
        times.append(unstored[0])
    return max(times, default=None)


def _buckets(client: AWApi | None) -> Mapping[str, Any] | None:
    if client is None:
        return None
    try:
        return client.get_buckets()
    except SourceUnavailable:
        return None


def _afk_spans(
    conn: sqlite3.Connection,
    client: AWApi | None,
    buckets: Mapping[str, Any] | None,
    start: datetime,
    end: datetime,
) -> list[AfkSpan]:
    spans = stored_afk_spans(conn, start, end)
    if client is not None and buckets is not None:
        try:
            spans.extend(newest_afk_spans(client, buckets))
        except SourceUnavailable:
            pass
    return spans


def _app_spans(
    conn: sqlite3.Connection,
    client: AWApi | None,
    buckets: Mapping[str, Any] | None,
    start: datetime,
    end: datetime,
    hostname: str,
) -> list[AppSpan]:
    spans = stored_app_spans(conn, start, end, hostname=hostname)
    if client is not None and buckets is not None:
        try:
            spans.extend(newest_app_spans(client, buckets, hostname=hostname))
        except SourceUnavailable:
            pass
    return spans


@dataclass(frozen=True)
class CaptureLiveness:
    """The agent's newest record, stored or still in the spool, and whether it looks alive."""

    last_record: datetime | None
    alive: Liveness
    spool_error: str | None = None


def active_spans(
    conn: sqlite3.Connection | None, client: AWApi | None, start: datetime, end: datetime
) -> list[Span]:
    """Collect the stretches aw-afk shows the user active, stored and in ActivityWatch's newest."""
    stored = [] if conn is None else stored_afk_spans(conn, start, end)
    if client is not None and (buckets := _buckets(client)) is not None:
        try:
            stored.extend(newest_afk_spans(client, buckets))
        except SourceUnavailable:
            pass
    return [(span.start, span.end) for span in stored if not span.afk]


def capture_liveness(
    conn: sqlite3.Connection | None,
    spool_folder: Path,
    *,
    now: datetime,
    active: Iterable[Span],
    watched_since: datetime,
    alive_within: timedelta,
) -> CaptureLiveness:
    """Judge the agent alive from its newest record, counting silence from watched_since on."""
    now = to_utc(now)
    try:
        unstored, spool_error = spool_backlog(spool_folder).newest, None
    except SpoolError as exc:
        unstored, spool_error = None, str(exc)
    stored = None if conn is None else newest_stored(conn, until=now)
    found = [record for record in (stored, unstored) if record is not None]
    if not found:
        return CaptureLiveness(None, Liveness.UNKNOWN, spool_error)
    at, kind = max(found, key=lambda record: record[0])
    alive = liveness(
        max(at, watched_since),
        now=now,
        paused=kind == PAUSED_KIND,
        active=active,
        alive_within=alive_within,
    )
    return CaptureLiveness(at, alive, spool_error)
