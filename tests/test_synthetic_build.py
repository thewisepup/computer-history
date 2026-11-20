from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from computer_history.sources import (
    WEB_SOURCE,
    extract_domain,
    reproject_signals,
    stored_afk_spans,
    stored_app_spans,
)
from computer_history.store import connect, content_digest, payload_values
from computer_history.synthetic import (
    DatasetInputs,
    Totals,
    backfill_feeds,
    build_dataset,
    poll_feeds,
)
from computer_history.synthetic.activitywatch import HOST

DEVELOPER_DAY = DatasetInputs(persona="developer", scenario="typical", tier="day", seed=1)


def test_the_same_inputs_build_the_same_dataset(tmp_path: Path) -> None:
    first = build_dataset(DEVELOPER_DAY, tmp_path / "first")
    second = build_dataset(DEVELOPER_DAY, tmp_path / "second")

    assert first.timeline == second.timeline
    assert first.rendered == second.rendered
    assert first.manifest.content_digest == second.manifest.content_digest
    assert first.manifest == second.manifest


def test_another_seed_builds_a_different_dataset(tmp_path: Path) -> None:
    first = build_dataset(DEVELOPER_DAY, tmp_path / "first")
    other = build_dataset(
        DatasetInputs(persona="developer", scenario="typical", tier="day", seed=2),
        tmp_path / "other",
    )

    assert first.manifest.content_digest != other.manifest.content_digest


def test_stored_time_equals_the_manifest(tmp_path: Path) -> None:
    dataset = build_dataset(DEVELOPER_DAY, tmp_path / "day")
    manifest = dataset.manifest
    conn = connect(dataset.db_path)
    try:
        stored = _stored_totals(conn, manifest.start, manifest.end)
        days = {
            day: _stored_totals(conn, lo, hi)
            for day, (lo, hi) in _local_days(manifest.start, manifest.end, manifest.timezone)
        }
    finally:
        conn.close()

    assert stored == manifest.total
    assert days == manifest.days
    assert manifest.total.foreground_app_seconds and manifest.total.afk_seconds > 0


def _stored_totals(conn: sqlite3.Connection, lo: datetime, hi: datetime) -> Totals:
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


def _seconds_by_key(
    spans: list[tuple[datetime, datetime, str | None]], lo: datetime, hi: datetime
) -> dict[str, float]:
    found: Counter[str] = Counter()
    for start, end, key in spans:
        overlap = min(end, hi) - max(start, lo)
        if key is not None and overlap > timedelta(0):
            found[key] += overlap // timedelta(milliseconds=1)
    return {key: ms / 1000 for key, ms in sorted(found.items())}


def _local_days(start: datetime, end: datetime, timezone: str):
    zone = ZoneInfo(timezone)
    day = start.astimezone(zone).date()
    while (lo := datetime.combine(day, time(), zone).astimezone(UTC)) < end:
        day += timedelta(days=1)
        yield (day - timedelta(days=1)).isoformat(), (lo, datetime.combine(day, time(), zone))


def test_ingesting_the_dataset_again_adds_nothing(tmp_path: Path) -> None:
    dataset = build_dataset(DEVELOPER_DAY, tmp_path / "day")
    conn = connect(dataset.db_path)
    try:
        polled = poll_feeds(conn, dataset.feeds, now=dataset.now)
        backfilled = backfill_feeds(
            conn, dataset.feeds, start=dataset.timeline.start, now=dataset.now
        )
        digest = content_digest(conn)
    finally:
        conn.close()

    assert (polled, backfilled) == (0, 0)
    assert digest == dataset.manifest.content_digest


def test_rebuilding_signals_gives_the_same_signals(tmp_path: Path) -> None:
    dataset = build_dataset(DEVELOPER_DAY, tmp_path / "day")
    conn = connect(dataset.db_path)
    try:
        rebuilt = reproject_signals(conn)
        digest = content_digest(conn)
    finally:
        conn.close()

    assert rebuilt.signals_before == rebuilt.signals_after > 0
    assert digest == dataset.manifest.content_digest
