from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from computer_history.sources.activitywatch import (
    AFK_SOURCE,
    AfkSpan,
    AppSpan,
    AWApi,
    discover_sources,
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
    attended_time,
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
    "active_time",
    "capture_health",
    "capture_liveness",
    "newest_record",
]


@dataclass(frozen=True)
class CaptureHealth:
    """What status reports about the capture agent. It has not reported until a record is stored."""

    reported: bool
    spool: SpoolBacklog | None
    spool_error: str | None
    last_capture: datetime | None = None
    last_record: datetime | None = None
    paused_since: datetime | None = None
    today: DayCounts = DayCounts()
    coverage: Coverage | None = None
    agreement: AppAgreement | None = None


def capture_health(
    conn: sqlite3.Connection,
    summaries: Iterable[SourceSummary],
    spool_folder: Path,
    client: AWApi | None,
    buckets: Mapping[str, Any] | None,
    *,
    now: datetime,
    window: timedelta,
    hostname: str,
    day_start: datetime,
    min_gap_seconds: float = 0,
) -> CaptureHealth:
    """Report on the agent from its stored records, its spool, aw-afk and aw-window, as of now.

    Only this host's window buckets count, and with a client and its bucket listing their newest
    events and AFK's do too.
    """
    now = to_utc(now)
    spool, spool_error = _backlog(spool_folder)
    summary = next((s for s in summaries if s.source == WINDOW_TEXT_SOURCE), None)
    stored = newest_stored(conn, until=now)
    unstored = None if spool is None else spool.newest
    newest = _newest(stored, unstored)
    if summary is None or summary.earliest_started_at is None or stored is None or newest is None:
        return CaptureHealth(False, spool, spool_error)

    end = stored[0] if spool is None or spool.unstored else now
    start = max(end - window, summary.earliest_started_at)
    day_start = to_utc(day_start)
    read_from = min(start - CAPTURE_TOLERANCE, day_start)

    records = stored_records(conn, read_from, now)
    before = newest_stored(conn, until=read_from)
    earlier = None if before is None else StoredRecord(*before)
    afk_from = min(read_from, newest.at)
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
        last_record=newest.at,
        paused_since=newest.at if newest.paused else None,
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


def _afk_spans(
    conn: sqlite3.Connection | None,
    client: AWApi | None,
    buckets: Mapping[str, Any] | None,
    start: datetime,
    end: datetime,
) -> list[AfkSpan]:
    spans = [] if conn is None else stored_afk_spans(conn, start, end)
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
    conn: sqlite3.Connection | None,
    client: AWApi | None,
    buckets: Mapping[str, Any] | None,
    start: datetime,
    end: datetime,
) -> list[Span]:
    """Collect the stretches aw-afk shows the user active, stored and in ActivityWatch's newest."""
    afk = _afk_spans(conn, client, buckets, start, end)
    return [(span.start, span.end) for span in afk if not span.afk]


@dataclass(frozen=True)
class NewestRecord:
    """When the agent's newest record, stored or still in the spool, was captured, and its kind."""

    at: datetime
    kind: str | None

    @property
    def paused(self) -> bool:
        return self.kind == PAUSED_KIND


def newest_record(
    conn: sqlite3.Connection | None, spool_folder: Path, *, now: datetime
) -> NewestRecord | None:
    """The agent's newest record up to now, stored or still in the spool; an unreadable spool
    counts as holding none."""
    return _stored_or_spooled(conn, spool_folder, to_utc(now))[0]


def active_time(
    conn: sqlite3.Connection | None, client: AWApi, start: datetime, end: datetime
) -> timedelta | None:
    """How long aw-afk shows the user active between two times, or None when ActivityWatch is
    unreachable or has no aw-afk bucket."""
    try:
        buckets = client.get_buckets()
    except SourceUnavailable:
        return None
    if not any(source.name == AFK_SOURCE for source in discover_sources(buckets)):
        return None
    return attended_time(active_spans(conn, client, buckets, start, end), start, end)


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
    newest, spool_error = _stored_or_spooled(conn, spool_folder, now)
    if newest is None:
        return CaptureLiveness(None, Liveness.UNKNOWN, spool_error)
    alive = liveness(
        max(newest.at, watched_since),
        now=now,
        paused=newest.paused,
        active=active,
        alive_within=alive_within,
    )
    return CaptureLiveness(newest.at, alive, spool_error)


def _stored_or_spooled(
    conn: sqlite3.Connection | None, spool_folder: Path, now: datetime
) -> tuple[NewestRecord | None, str | None]:
    spool, spool_error = _backlog(spool_folder)
    stored = None if conn is None else newest_stored(conn, until=now)
    return _newest(stored, None if spool is None else spool.newest), spool_error


def _backlog(spool_folder: Path) -> tuple[SpoolBacklog | None, str | None]:
    try:
        return spool_backlog(spool_folder), None
    except SpoolError as exc:
        return None, str(exc)


def _newest(
    stored: tuple[datetime, str | None] | None, unstored: tuple[datetime, str] | None
) -> NewestRecord | None:
    found = [record for record in (stored, unstored) if record is not None]
    if not found:
        return None
    at, kind = max(found, key=lambda record: record[0])
    return NewestRecord(at, kind)
