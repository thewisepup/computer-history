from __future__ import annotations

from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

import pytest
from store_answers import local_days, stored_days, stored_gaps, stored_totals

from computer_history.sources import AFK_SOURCE, AX_TEXT_SOURCE, WEB_SOURCE, WINDOW_SOURCE
from computer_history.store import connect, source_summary
from computer_history.synthetic import (
    HEAVY,
    PERSONAS,
    RENDERERS,
    TIERS,
    DatasetInputs,
    FaultKind,
    Stretch,
    StretchKind,
    Timeline,
    Totals,
    build_dataset,
    build_timeline,
    generate_timeline,
)
from computer_history.synthetic.days import live
from computer_history.synthetic.seeds import part_random
from computer_history.text import extract_domain

pytestmark = pytest.mark.dataset

TARGET_EVENTS = 5000
TARGET_MIX = {WINDOW_SOURCE: 0.53, WEB_SOURCE: 0.36, AX_TEXT_SOURCE: 0.12, AFK_SOURCE: 0.01}
ACTIVITYWATCH = (WINDOW_SOURCE, WEB_SOURCE, AFK_SOURCE)
SEEDS = range(1, 6)
MONDAY = date(2026, 1, 5)


def rendered_counts(inputs: DatasetInputs) -> Counter[str]:
    timeline = generate_timeline(inputs)
    counts: Counter[str] = Counter()
    for renderer in RENDERERS:
        counts.update(
            renderer.render(timeline, part_random(inputs.seed, renderer.name)).observation_counts()
        )
    return counts


def developer_day(seed: int) -> DatasetInputs:
    return DatasetInputs("developer", "typical", "day", seed=seed, start=MONDAY)


@pytest.mark.parametrize(("tier", "days"), [("day", 1), ("week", 7), ("month", 30), ("year", 365)])
def test_each_tier_covers_its_number_of_local_days(tier: str, days: int) -> None:
    timeline = generate_timeline(DatasetInputs("developer", "typical", tier, seed=1, start=MONDAY))
    covered = [day for day, _ in local_days(timeline.start, timeline.end, timeline.timezone)]

    assert TIERS[tier] == days
    assert covered == [_day(offset) for offset in range(days)]


def test_the_developer_day_makes_about_5000_events() -> None:
    first = sum(rendered_counts(developer_day(1)).values())
    typical = mean(sum(rendered_counts(developer_day(seed)).values()) for seed in range(1, 11))

    assert abs(first / TARGET_EVENTS - 1) <= 0.15, first
    assert abs(typical / TARGET_EVENTS - 1) <= 0.15, typical


def test_the_developer_day_splits_activitywatch_events_in_the_target_mix() -> None:
    counts = rendered_counts(developer_day(1))
    events = sum(counts[stream] for stream in ACTIVITYWATCH)
    target = sum(TARGET_MIX[stream] for stream in ACTIVITYWATCH)
    shares = {stream: round(counts[stream] / events, 3) for stream in ACTIVITYWATCH}
    targets = {stream: round(TARGET_MIX[stream] / target, 3) for stream in ACTIVITYWATCH}

    for stream in ACTIVITYWATCH:
        assert abs(shares[stream] - targets[stream]) <= 0.05, (shares, targets)


@pytest.mark.xfail(
    strict=True,
    reason="the agent captures on every focus change, so captured text tracks window events",
)
def test_the_developer_day_makes_the_target_mix_across_every_source() -> None:
    counts = rendered_counts(developer_day(1))
    events = sum(counts.values())
    shares = {stream: round(counts[stream] / events, 3) for stream in TARGET_MIX}

    for stream, target in TARGET_MIX.items():
        assert abs(shares[stream] - target) <= 0.05, (shares, TARGET_MIX)


def _heavy_ratios(persona: str) -> tuple[float, float]:
    ordinary = [
        rendered_counts(DatasetInputs(persona, "typical", "day", s, start=MONDAY)) for s in SEEDS
    ]
    heavy = [
        rendered_counts(DatasetInputs(persona, "typical", "day", s, start=MONDAY, heavy=HEAVY))
        for s in SEEDS
    ]
    windows = sum(c[WINDOW_SOURCE] for c in heavy) / sum(c[WINDOW_SOURCE] for c in ordinary)
    events = sum(sum(c.values()) for c in heavy) / sum(sum(c.values()) for c in ordinary)
    return windows, events


def test_heavy_roughly_doubles_the_events_of_a_developer_workday() -> None:
    assert 1.7 <= _heavy_ratios("developer")[1] <= 2.5


@pytest.mark.parametrize("persona", sorted(PERSONAS))
def test_heavy_roughly_doubles_the_window_switches_of_a_workday(persona: str) -> None:
    assert 1.7 <= _heavy_ratios(persona)[0] <= 2.5


@pytest.mark.parametrize("persona", sorted(PERSONAS))
def test_heavy_fills_weekends_and_doubles_text_with_the_same_apps_and_sites(persona: str) -> None:
    week = DatasetInputs(persona, "typical", "week", seed=1, start=MONDAY)
    ordinary = generate_timeline(week)
    heavy = generate_timeline(replace(week, heavy=HEAVY))
    text_ratio = mean(len(s.text) for s in heavy.stretches if s.active) / mean(
        len(s.text) for s in ordinary.stretches if s.active
    )

    assert _active_days(ordinary) == [_day(offset) for offset in range(5)]
    assert _active_days(heavy) == [_day(offset) for offset in range(7)]
    assert 1.7 <= text_ratio <= 2.3, text_ratio
    assert _apps_and_domains(heavy) == _apps_and_domains(ordinary)


def _day(offset: int) -> str:
    return (MONDAY + timedelta(days=offset)).isoformat()


def _active_days(timeline: Timeline) -> list[str]:
    return [
        day
        for day, (lo, hi) in local_days(timeline.start, timeline.end, timeline.timezone)
        if any(s.active and s.start < hi and s.end > lo for s in timeline.stretches)
    ]


def _apps_and_domains(timeline: Timeline) -> tuple[set[str], set[str | None]]:
    active = [s for s in timeline.stretches if s.active]
    return {s.app for s in active}, {extract_domain(s.url) for s in active}


@pytest.mark.parametrize("heavy", [0.5, float("nan"), float("inf"), True])
def test_a_heavy_factor_that_is_not_a_finite_number_of_at_least_one_is_refused(
    heavy: float,
) -> None:
    with pytest.raises(ValueError, match="finite number >= 1"):
        DatasetInputs("developer", "typical", "day", seed=1, heavy=heavy)


def test_a_whole_number_heavy_factor_is_recorded_as_the_same_float() -> None:
    assert DatasetInputs("developer", "typical", "day", seed=1, heavy=2).heavy == HEAVY
    assert isinstance(DatasetInputs("developer", "typical", "day", seed=1, heavy=2).heavy, float)


CONTENT_CREATOR_WEEK = DatasetInputs("content-creator", "typical", "week", seed=1, start=MONDAY)


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
    assert list(manifest.days) == [_day(offset) for offset in range(TIERS["week"])]
    assert {"CapCut", "Google Chrome"} <= set(manifest.total.foreground_app_seconds)
    assert "studio.youtube.com" in manifest.total.foreground_domain_seconds
    assert manifest.days[_day(5)].foreground_app_seconds == {}


def test_the_content_creator_week_builds_the_same_every_time(tmp_path: Path) -> None:
    first = build_dataset(CONTENT_CREATOR_WEEK, tmp_path / "first")
    second = build_dataset(CONTENT_CREATOR_WEEK, tmp_path / "second")

    assert first.timeline == second.timeline
    assert first.rendered == second.rendered
    assert first.manifest == second.manifest


@pytest.mark.parametrize(
    ("persona", "tier", "heavy"),
    [(persona, "week", 1.0) for persona in sorted(PERSONAS)]
    + [(persona, "day", HEAVY) for persona in sorted(PERSONAS)],
)
def test_the_messy_scenario_builds_for_every_persona_and_matches_its_manifest(
    tmp_path: Path, persona: str, tier: str, heavy: float
) -> None:
    inputs = DatasetInputs(persona, "messy", tier, seed=1, start=MONDAY, heavy=heavy)
    dataset = build_dataset(inputs, tmp_path / "messy")
    conn = connect(dataset.db_path)
    try:
        days = stored_days(conn, dataset.manifest)
        counts = {row.source: row.observation_count for row in source_summary(conn)}
    finally:
        conn.close()
    gaps, _, afk = stored_gaps(dataset)
    explained = dataset.manifest.explained

    assert days == dataset.manifest.days
    assert counts == dataset.manifest.observations
    assert len(dataset.timeline.faults) == len(FaultKind)
    assert gaps == dataset.manifest.unobserved
    assert sorted(gap.kind for gap in explained) == ["excluded", "paused"]
    for gap in explained:
        assert not [g for g in gaps[AX_TEXT_SOURCE] if g.start < gap.end and gap.start < g.end]
    for gap in gaps[AX_TEXT_SOURCE]:
        assert any(not s.afk and s.start <= gap.start and gap.end <= s.end for s in afk)


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

AROUND_MIDNIGHT_COUNTS = {"aw-afk": 1, "aw-web": 1, "aw-window": 2, "ax-text": 50}


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
    assert dataset.manifest.observations == AROUND_MIDNIGHT_COUNTS
    assert counts == AROUND_MIDNIGHT_COUNTS


@pytest.mark.parametrize("seed", SEEDS)
def test_a_late_evening_stops_at_local_midnight(seed: int) -> None:
    developer = PERSONAS["developer"]
    night_owl = replace(
        developer,
        rhythm=replace(developer.rhythm, evening_chance=1.0, evening_start=time(23, 45)),
    )
    stretches = live(night_owl, MONDAY, 2, "America/Los_Angeles", part_random(seed, "night owl"))
    midnights = [
        datetime.combine(MONDAY + timedelta(days=offset), time(), PACIFIC) for offset in (1, 2)
    ]

    assert stretches[-1].end == midnights[-1]
    assert not [s for s in stretches if s.active and any(s.start < m < s.end for m in midnights)]
