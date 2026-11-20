"""What the store reports for a dataset, in the manifest's terms, read through the real store."""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from computer_history.sources import (
    AFK_SOURCE,
    AX_TEXT_SOURCE,
    WEB_SOURCE,
    WINDOW_SOURCE,
    capture_coverage,
    extract_domain,
    stored_afk_spans,
    stored_app_spans,
    stored_records,
)
from computer_history.store import Gap, connect, find_gaps, payload_values
from computer_history.synthetic import DATABASE_NAME, MANIFEST_NAME, Dataset, Manifest, Totals
from computer_history.synthetic.activitywatch import HOST
from computer_history.synthetic.spool import RENDERED_SPOOL_FOLDER

DATASET_FILES = sorted([DATABASE_NAME, MANIFEST_NAME, RENDERED_SPOOL_FOLDER])


def stored_totals(conn: sqlite3.Connection, lo: datetime, hi: datetime) -> Totals:
    """Foreground, attended and AFK time the store reports between lo and hi."""
    apps = [(s.start, s.end, s.app) for s in stored_app_spans(conn, lo, hi, hostname=HOST)]
    afk = stored_afk_spans(conn, lo, hi)
    web = payload_values(conn, WEB_SOURCE, lo, hi, ("$.data.url",))
    domains = [(row.started_at, row.ended_at, extract_domain(row.values[0])) for row in web]
    present = [(span.start, span.end) for span in afk if not span.afk]
    attended = [
        (max(start, p_start), min(end, p_end), app)
        for start, end, app in apps
        for p_start, p_end in present
    ]
    away = [(span.start, span.end, "afk") for span in afk if span.afk]
    return Totals(
        foreground_app_seconds=_seconds_by_key(apps, lo, hi),
        foreground_domain_seconds=_seconds_by_key(domains, lo, hi),
        attended_app_seconds=_seconds_by_key(attended, lo, hi),
        afk_seconds=_seconds_by_key(away, lo, hi).get("afk", 0.0),
    )


def stored_days(conn: sqlite3.Connection, manifest: Manifest) -> dict[str, Totals]:
    """The stored totals for each local day of the manifest's range."""
    return {
        day: stored_totals(conn, lo, hi)
        for day, (lo, hi) in local_days(manifest.start, manifest.end, manifest.timezone)
    }


def local_days(
    start: datetime, end: datetime, timezone: str
) -> Iterator[tuple[str, tuple[datetime, datetime]]]:
    """Each local day from start to end, with the UTC times it begins and ends."""
    zone = ZoneInfo(timezone)
    day = start.astimezone(zone).date()
    while (lo := datetime.combine(day, time(), zone).astimezone(UTC)) < end:
        day += timedelta(days=1)
        yield (day - timedelta(days=1)).isoformat(), (lo, datetime.combine(day, time(), zone))


def _seconds_by_key(
    spans: list[tuple[datetime, datetime, str | None]], lo: datetime, hi: datetime
) -> dict[str, float]:
    found: Counter[str] = Counter()
    for start, end, key in spans:
        overlap = min(end, hi) - max(start, lo)
        if key is not None and overlap > timedelta(0):
            found[key] += overlap // timedelta(milliseconds=1)
    return {key: ms / 1000 for key, ms in sorted(found.items())}


def stored_gaps(dataset: Dataset) -> tuple[dict[str, tuple[Gap, ...]], list, list]:
    """Each source's unobserved gaps over the range, plus the capture records and AFK spans read."""
    start, end = dataset.timeline.start, dataset.timeline.end
    conn = connect(dataset.db_path)
    try:
        gaps = {
            source: tuple(find_gaps(conn, source, start, end, min_gap_seconds=1))
            for source in (WINDOW_SOURCE, AFK_SOURCE)
        }
        records = stored_records(conn, start, end)
        afk = stored_afk_spans(conn, start, end)
    finally:
        conn.close()
    coverage = capture_coverage(
        records,
        active=[(s.start, s.end) for s in afk if not s.afk],
        known=[(s.start, s.end) for s in afk],
        start=start,
        end=end,
        paused_at_start=False,
        min_gap_seconds=1,
    )
    return {**gaps, AX_TEXT_SOURCE: coverage.unobserved}, records, afk
