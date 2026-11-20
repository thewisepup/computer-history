from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

import pytest
from store_answers import local_days, stored_days, stored_totals

from computer_history.sources import AFK_SOURCE, WEB_SOURCE, WINDOW_SOURCE
from computer_history.sources.ax_text import AX_TEXT_SOURCE as TEXT_SOURCE
from computer_history.store import connect, source_summary
from computer_history.synthetic import (
    HEAVY,
    PERSONAS,
    RENDERERS,
    TIERS,
    DatasetInputs,
    Stretch,
    StretchKind,
    Timeline,
    Totals,
    build_dataset,
    build_timeline,
    generate_timeline,
)
from computer_history.synthetic.seeds import part_random
from computer_history.text import extract_domain

TARGET_EVENTS = 5000
TARGET_MIX = {WINDOW_SOURCE: 0.53, WEB_SOURCE: 0.36, TEXT_SOURCE: 0.12, AFK_SOURCE: 0.01}
ACTIVITYWATCH = (WINDOW_SOURCE, WEB_SOURCE, AFK_SOURCE)
SEEDS = range(1, 6)


def rendered_counts(inputs: DatasetInputs) -> Counter[str]:
    timeline = generate_timeline(inputs)
    counts: Counter[str] = Counter()
    for renderer in RENDERERS:
        counts.update(
            renderer.render(timeline, part_random(inputs.seed, renderer.name)).observation_counts()
        )
    return counts


def developer_day(seed: int) -> DatasetInputs:
    return DatasetInputs(persona="developer", scenario="typical", tier="day", seed=seed)


@pytest.mark.parametrize(("tier", "days"), [("day", 1), ("week", 7), ("month", 30), ("year", 365)])
def test_each_tier_covers_its_number_of_local_days(tier: str, days: int) -> None:
    timeline = generate_timeline(DatasetInputs("developer", "typical", tier, seed=1))
    covered = [day for day, _ in local_days(timeline.start, timeline.end, timeline.timezone)]

    assert TIERS[tier] == days
    assert len(covered) == days
    assert covered[0] == "2026-01-05"


@pytest.mark.parametrize("seed", SEEDS)
def test_the_developer_day_makes_its_share_of_activitywatch_events(seed: int) -> None:
    counts = rendered_counts(developer_day(seed))
    events = sum(counts[stream] for stream in ACTIVITYWATCH)
    expected = TARGET_EVENTS * sum(TARGET_MIX[stream] for stream in ACTIVITYWATCH)
    shares = {stream: round(counts[stream] / TARGET_EVENTS, 3) for stream in ACTIVITYWATCH}

    assert abs(events / expected - 1) <= 0.15, (events, expected)
    for stream in ACTIVITYWATCH:
        assert abs(shares[stream] - TARGET_MIX[stream]) <= 0.05, (shares, TARGET_MIX)


@pytest.mark.parametrize("seed", SEEDS)
def test_the_developer_day_makes_about_5000_events_in_the_target_mix(seed: int) -> None:
    rendered = {stream for renderer in RENDERERS for stream in renderer.streams}
    if TEXT_SOURCE not in rendered:
        pytest.skip("captured text arrives with the spool renderer")
    counts = rendered_counts(developer_day(seed))
    events = sum(counts.values())
    shares = {stream: round(counts[stream] / events, 3) for stream in TARGET_MIX}

    assert abs(events / TARGET_EVENTS - 1) <= 0.15, events
    for stream, target in TARGET_MIX.items():
        assert abs(shares[stream] - target) <= 0.05, (shares, TARGET_MIX)


@pytest.mark.parametrize("persona", sorted(PERSONAS))
def test_heavy_roughly_doubles_the_events_of_a_workday(persona: str) -> None:
    ordinary = [rendered_counts(DatasetInputs(persona, "typical", "day", s)) for s in SEEDS]
    heavy = [
        rendered_counts(DatasetInputs(persona, "typical", "day", s, heavy=HEAVY)) for s in SEEDS
    ]
    ratio = sum(sum(c.values()) for c in heavy) / sum(sum(c.values()) for c in ordinary)

    assert 1.7 <= ratio <= 2.5, ratio


@pytest.mark.parametrize("persona", sorted(PERSONAS))
def test_heavy_fills_weekends_and_doubles_text_with_the_same_apps_and_sites(persona: str) -> None:
    ordinary = generate_timeline(DatasetInputs(persona, "typical", "week", seed=1))
    heavy = generate_timeline(DatasetInputs(persona, "typical", "week", seed=1, heavy=HEAVY))
    text_ratio = mean(len(s.text) for s in heavy.stretches if s.active) / mean(
        len(s.text) for s in ordinary.stretches if s.active
    )

    assert _active_days(ordinary) == [f"2026-01-{day:02d}" for day in range(5, 10)]
    assert _active_days(heavy) == [f"2026-01-{day:02d}" for day in range(5, 12)]
    assert 1.7 <= text_ratio <= 2.3, text_ratio
    assert _apps_and_domains(heavy) == _apps_and_domains(ordinary)


def _active_days(timeline: Timeline) -> list[str]:
    return [
        day
        for day, (lo, hi) in local_days(timeline.start, timeline.end, timeline.timezone)
        if any(s.active and s.start < hi and s.end > lo for s in timeline.stretches)
    ]


def _apps_and_domains(timeline: Timeline) -> tuple[set[str], set[str | None]]:
    active = [s for s in timeline.stretches if s.active]
    return {s.app for s in active}, {extract_domain(s.url) for s in active}


def test_a_heavy_factor_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        DatasetInputs("developer", "typical", "day", seed=1, heavy=0.5)


CONTENT_CREATOR_WEEK = DatasetInputs("content-creator", "typical", "week", seed=1)


def test_the_content_creator_week_reports_what_its_manifest_says(tmp_path: Path) -> None:
    dataset = build_dataset(CONTENT_CREATOR_WEEK, tmp_path / "week")
    manifest = dataset.manifest
    conn = connect(dataset.db_path)
    try:
        total = stored_totals(conn, manifest.start, manifest.end)
        days = stored_days(conn, manifest)
        counts = {row.source: row.observation_count for row in source_summary(conn)}
    finally:
        conn.close()

    assert total == manifest.total
    assert days == manifest.days
    assert counts == manifest.observations
    assert len(manifest.days) == 7
    assert {"CapCut", "Google Chrome"} <= set(manifest.total.foreground_app_seconds)
    assert "studio.youtube.com" in manifest.total.foreground_domain_seconds
    assert manifest.days["2026-01-10"].foreground_app_seconds == {}


def test_the_content_creator_week_builds_the_same_every_time(tmp_path: Path) -> None:
    first = build_dataset(CONTENT_CREATOR_WEEK, tmp_path / "first")
    second = build_dataset(CONTENT_CREATOR_WEEK, tmp_path / "second")

    assert first.timeline == second.timeline
    assert first.rendered == second.rendered
    assert first.manifest == second.manifest


def pacific(day: int, hour: int, minute: int) -> datetime:
    return datetime(2026, 1, day, hour, minute, tzinfo=PACIFIC).astimezone(UTC)


PACIFIC = ZoneInfo("America/Los_Angeles")
ISSUE = "https://github.com/acme/ledger/issues/7"
ACROSS_MIDNIGHT = Timeline(
    pacific(5, 0, 0),
    pacific(7, 0, 0),
    "America/Los_Angeles",
    (
        Stretch(pacific(5, 0, 0), pacific(5, 23, 50), kind=StretchKind.ASLEEP),
        Stretch(pacific(5, 23, 50), pacific(6, 0, 10), app="Cursor", title="late.py"),
        Stretch(
            pacific(6, 0, 10), pacific(6, 0, 15), app="Google Chrome", title="Issue 7", url=ISSUE
        ),
        Stretch(pacific(6, 0, 15), pacific(7, 0, 0), kind=StretchKind.ASLEEP),
    ),
)
BEFORE_MIDNIGHT = Totals(
    foreground_app_seconds={"Cursor": 600.0},
    foreground_domain_seconds={},
    attended_app_seconds={"Cursor": 600.0},
    afk_seconds=0.0,
)
AFTER_MIDNIGHT = Totals(
    foreground_app_seconds={"Cursor": 600.0, "Google Chrome": 300.0},
    foreground_domain_seconds={"github.com": 300.0},
    attended_app_seconds={"Cursor": 600.0, "Google Chrome": 300.0},
    afk_seconds=0.0,
)


def test_a_session_across_local_midnight_splits_between_the_two_days(tmp_path: Path) -> None:
    dataset = build_timeline(ACROSS_MIDNIGHT, tmp_path / "late", seed=1)
    conn = connect(dataset.db_path)
    try:
        days = stored_days(conn, dataset.manifest)
        counts = {row.source: row.observation_count for row in source_summary(conn)}
    finally:
        conn.close()
    expected = {"2026-01-05": BEFORE_MIDNIGHT, "2026-01-06": AFTER_MIDNIGHT}

    assert dataset.manifest.days == expected
    assert days == expected
    assert dataset.manifest.total.foreground_app_seconds == {
        "Cursor": 1200.0,
        "Google Chrome": 300.0,
    }
    assert dataset.manifest.observations == {"aw-afk": 1, "aw-web": 1, "aw-window": 2}
    assert counts == {"aw-afk": 1, "aw-web": 1, "aw-window": 2}
