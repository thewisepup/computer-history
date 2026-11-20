from __future__ import annotations

import random
from collections import Counter
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from computer_history.sources import (
    AFK_SOURCE,
    AX_TEXT_SOURCE,
    WEB_SOURCE,
    WINDOW_SOURCE,
    capture_coverage,
    stored_afk_spans,
    stored_records,
)
from computer_history.store import Gap, connect, find_gaps, payload_values, source_summary
from computer_history.synthetic import (
    CaptureCounts,
    DatasetInputs,
    ExplainedGap,
    Fault,
    FaultKind,
    Stretch,
    StretchKind,
    Timeline,
    Totals,
    build_dataset,
    build_timeline,
    generate_timeline,
)
from computer_history.synthetic import build as synthetic_build
from computer_history.synthetic.activitywatch import BUCKETS, ActivityWatchRenderer
from computer_history.synthetic.spool import SpoolRenderer

DAY = datetime(2026, 1, 5, tzinfo=UTC)
PR = "https://github.com/acme/ledger/pull/1"


def at(hour: int, minute: int, second: int = 0) -> datetime:
    return DAY + timedelta(hours=hour, minutes=minute, seconds=second)


@pytest.fixture
def plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        synthetic_build,
        "RENDERERS",
        (ActivityWatchRenderer(), SpoolRenderer(hostile_windows_per_day=0)),
    )


FAULTY_HOUR = Timeline(
    at(9, 0),
    at(10, 0),
    "UTC",
    (
        Stretch(at(9, 0), at(9, 20), app="Cursor", title="a.py"),
        Stretch(at(9, 20), at(9, 25), app="1Password", title="1Password"),
        Stretch(at(9, 25), at(9, 55), app="Google Chrome", title="Pull #1", url=PR),
        Stretch(at(9, 55), at(10, 0), kind=StretchKind.ASLEEP),
    ),
    (
        Fault(at(9, 5), at(9, 10), FaultKind.PAUSED),
        Fault(at(9, 12), at(9, 16), FaultKind.PERMISSION_LOST),
        Fault(at(9, 20), at(9, 25), FaultKind.EXCLUDED),
        Fault(at(9, 30), at(9, 40), FaultKind.AW_DOWN),
        Fault(at(9, 45), at(9, 50), FaultKind.AGENT_DOWN),
    ),
)
FAULTY_HOUR_TOTALS = Totals(
    foreground_app_seconds={"1Password": 300.0, "Cursor": 1200.0, "Google Chrome": 1200.0},
    foreground_domain_seconds={"github.com": 1200.0},
    attended_app_seconds={"1Password": 300.0, "Cursor": 1200.0, "Google Chrome": 1200.0},
    afk_seconds=0.0,
)
FAULTY_HOUR_COUNTS = {"aw-afk": 2, "aw-web": 2, "aw-window": 4, "ax-text": 84}
FAULTY_HOUR_CAPTURES = CaptureCounts(
    kinds={"capture": 72, "excluded": 10, "paused": 1, "resumed": 1},
    triggers={"app": 2, "heartbeat": 80},
    apps={"1Password": 10, "Cursor": 22, "Google Chrome": 50},
)
FAULTY_HOUR_UNOBSERVED = {
    AFK_SOURCE: (Gap(at(9, 30), at(9, 40)), Gap(at(9, 55), at(10, 0))),
    AX_TEXT_SOURCE: (Gap(at(9, 12, 31), at(9, 15)), Gap(at(9, 45, 31), at(9, 49, 1))),
    WINDOW_SOURCE: (Gap(at(9, 30), at(9, 40)), Gap(at(9, 55), at(10, 0))),
}
FAULTY_HOUR_EXPLAINED = (
    ExplainedGap(at(9, 5), at(9, 10), "paused"),
    ExplainedGap(at(9, 20), at(9, 25), "excluded"),
)


def _heartbeats(first: datetime, until: datetime) -> list[datetime]:
    beats = (until - first) // timedelta(seconds=30) + 1
    return [first + k * timedelta(seconds=30) for k in range(beats)]


FAULTY_HOUR_RECORDS = [
    *((moment, "capture", "Cursor") for moment in _heartbeats(at(9, 0, 1), at(9, 4, 31))),
    (at(9, 5), "paused", None),
    (at(9, 10), "resumed", None),
    *((moment, "capture", "Cursor") for moment in _heartbeats(at(9, 10, 1), at(9, 11, 31))),
    *((moment, "capture", "Cursor") for moment in _heartbeats(at(9, 16), at(9, 19, 30))),
    *((moment, "excluded", "1Password") for moment in _heartbeats(at(9, 20, 1), at(9, 24, 31))),
    *((moment, "capture", "Google Chrome") for moment in _heartbeats(at(9, 25, 1), at(9, 44, 31))),
    *((moment, "capture", "Google Chrome") for moment in _heartbeats(at(9, 50, 1), at(9, 54, 31))),
]


def test_a_hand_worked_hour_of_faults_reports_the_gaps_worked_out_by_hand(
    tmp_path: Path, plain_text: None
) -> None:
    dataset = build_timeline(FAULTY_HOUR, tmp_path / "hour", seed=1)
    manifest = dataset.manifest
    start, end = FAULTY_HOUR.start, FAULTY_HOUR.end
    conn = connect(dataset.db_path)
    try:
        gaps = {
            source: tuple(find_gaps(conn, source, start, end, min_gap_seconds=1))
            for source in (WINDOW_SOURCE, AFK_SOURCE)
        }
        records = stored_records(conn, start, end)
        afk = stored_afk_spans(conn, start, end)
        counts = {row.source: row.observation_count for row in source_summary(conn)}
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

    assert manifest.total == FAULTY_HOUR_TOTALS
    assert manifest.observations == counts == FAULTY_HOUR_COUNTS
    assert manifest.captures == FAULTY_HOUR_CAPTURES
    assert manifest.unobserved == FAULTY_HOUR_UNOBSERVED
    assert manifest.explained == FAULTY_HOUR_EXPLAINED
    assert {**gaps, AX_TEXT_SOURCE: coverage.unobserved} == FAULTY_HOUR_UNOBSERVED
    assert [(r.at, r.kind, r.app) for r in records] == FAULTY_HOUR_RECORDS
    assert Counter(r.kind for r in records) == FAULTY_HOUR_CAPTURES.kinds
    assert not any(s.afk for s in afk)


MESSY_DAY = DatasetInputs(persona="developer", scenario="messy", tier="day", seed=1)
LOCAL = ZoneInfo("America/Los_Angeles")


def _local(moment: datetime) -> time:
    return moment.astimezone(LOCAL).time()


def test_the_messy_scenario_places_every_happening_on_its_one_day() -> None:
    timeline = generate_timeline(MESSY_DAY)
    faults = {fault.kind: fault for fault in timeline.faults}
    excluded = faults[FaultKind.EXCLUDED]
    asleep = [s for s in timeline.stretches if not s.active]
    away = [s for s in timeline.stretches if s.active and s.afk]

    assert sorted(kind.value for kind in faults) == sorted(kind.value for kind in FaultKind)
    assert len(timeline.faults) == len(FaultKind)
    outage = faults[FaultKind.AW_DOWN]
    assert outage.end - outage.start >= timedelta(hours=2)
    assert time(9, 30) <= _local(outage.start) and _local(outage.end) <= time(12, 0)
    assert [(s.start, s.end, s.app) for s in timeline.stretches if s.app == "1Password"] == [
        (excluded.start, excluded.end, "1Password")
    ]
    assert any(_local(s.start) == time(12, 30) and _local(s.end) == time(12, 50) for s in asleep)
    assert any(s.end == timeline.end and s.end - s.start >= timedelta(hours=1) for s in away)
    assert generate_timeline(DEVELOPER_TYPICAL).faults == ()


DEVELOPER_TYPICAL = DatasetInputs(persona="developer", scenario="typical", tier="day", seed=1)


def _store_gaps(dataset) -> tuple[dict[str, tuple[Gap, ...]], list, list]:
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


def _within(inner: tuple[datetime, datetime], gaps: tuple[Gap, ...]) -> bool:
    return any(gap.start <= inner[0] and inner[1] <= gap.end for gap in gaps)


def _overlaps(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> bool:
    return max(a[0], b[0]) < min(a[1], b[1])


def test_on_a_messy_day_every_source_reports_the_manifests_gaps_and_none_as_idle(
    tmp_path: Path,
) -> None:
    dataset = build_dataset(MESSY_DAY, tmp_path / "messy")
    manifest = dataset.manifest
    gaps, _, afk = _store_gaps(dataset)
    outages = dataset.timeline.faults_of(FaultKind.AW_DOWN)
    agent_out = dataset.timeline.faults_of(FaultKind.AGENT_DOWN, FaultKind.PERMISSION_LOST)

    assert gaps == manifest.unobserved
    for outage in outages:
        span = (outage.start, outage.end)
        assert _within(span, gaps[WINDOW_SOURCE]) and _within(span, gaps[AFK_SOURCE])
        assert not [s for s in afk if _overlaps((s.start, s.end), span)]
    for fault in agent_out:
        span = (fault.start, fault.end)
        assert any(_overlaps((g.start, g.end), span) for g in gaps[AX_TEXT_SOURCE])
    for gap in gaps[AX_TEXT_SOURCE]:
        assert any(not s.afk and s.start <= gap.start and gap.end <= s.end for s in afk)


def test_on_a_messy_day_capture_coverage_explains_the_exclusion_and_the_pause(
    tmp_path: Path,
) -> None:
    dataset = build_dataset(MESSY_DAY, tmp_path / "messy")
    gaps, records, _ = _store_gaps(dataset)
    explained = dataset.manifest.explained
    by_kind = {gap.kind: gap for gap in explained}

    assert sorted(by_kind) == ["excluded", "paused"] and len(explained) == 2
    for gap in explained:
        span = (gap.start, gap.end)
        assert not any(_overlaps((g.start, g.end), span) for g in gaps[AX_TEXT_SOURCE])
    pause, exclusion = by_kind["paused"], by_kind["excluded"]
    assert [(r.at, r.kind) for r in records if r.kind in ("paused", "resumed")] == [
        (pause.start, "paused"),
        (pause.end, "resumed"),
    ]
    inside = [r for r in records if exclusion.start <= r.at < exclusion.end]
    assert inside and {(r.kind, r.app) for r in inside} == {("excluded", "1Password")}
    assert not [r for r in records if pause.start < r.at < pause.end]
    assert Counter(r.kind for r in records) == dataset.manifest.captures.kinds
    stored = CaptureCounts(
        kinds=dict(sorted(Counter(r.kind for r in records).items())),
        triggers=dict(sorted(Counter(v for v in _triggers(dataset) if v is not None).items())),
        apps=dict(sorted(Counter(r.app for r in records if r.app is not None).items())),
    )
    assert stored == dataset.manifest.captures


def _triggers(dataset) -> list[str | None]:
    conn = connect(dataset.db_path)
    try:
        rows = payload_values(
            conn, AX_TEXT_SOURCE, dataset.timeline.start, dataset.timeline.end, ("$.trigger",)
        )
    finally:
        conn.close()
    return [row.values[0] for row in rows]


OUTAGE_MORNING = (
    Stretch(at(9, 0), at(9, 10), app="Google Chrome", title="Pull #1", url=PR),
    Stretch(at(9, 10), at(9, 20), app="Cursor", title="a.py"),
)


def _served(timeline: Timeline) -> dict[str, list[tuple[datetime, datetime]]]:
    rendered = ActivityWatchRenderer().render(timeline, random.Random(0))
    return {
        BUCKETS[bucket][2]: [(e.start, e.end) for e in events]
        for bucket, events in rendered.events.items()
    }


def test_an_outage_of_one_watcher_leaves_the_other_streams_whole() -> None:
    web_down = Fault(at(9, 5), at(9, 15), FaultKind.AW_DOWN, sources=(WEB_SOURCE,))
    timeline = Timeline(at(9, 0), at(9, 20), "UTC", OUTAGE_MORNING, (web_down,))

    assert _served(timeline) == {
        AFK_SOURCE: [(at(9, 0), at(9, 20))],
        WEB_SOURCE: [(at(9, 0), at(9, 5))],
        WINDOW_SOURCE: [(at(9, 0), at(9, 10)), (at(9, 10), at(9, 20))],
    }


def test_an_activitywatch_outage_records_nothing_and_restarts_like_a_wake() -> None:
    down = Fault(at(9, 5), at(9, 15), FaultKind.AW_DOWN)
    timeline = Timeline(at(9, 0), at(9, 20), "UTC", OUTAGE_MORNING, (down,))

    assert _served(timeline) == {
        AFK_SOURCE: [(at(9, 0), at(9, 5)), (at(9, 15), at(9, 20))],
        WEB_SOURCE: [(at(9, 0), at(9, 5))],
        WINDOW_SOURCE: [(at(9, 0), at(9, 5)), (at(9, 15), at(9, 20))],
    }


@pytest.mark.parametrize(
    ("fault", "error"),
    [
        (Fault(at(8, 59), at(9, 5), FaultKind.PAUSED), "not inside the range"),
        (Fault(at(9, 5), at(9, 5), FaultKind.PAUSED), "not inside the range"),
    ],
    ids=["before-the-range", "empty"],
)
def test_a_fault_outside_the_range_is_refused(fault: Fault, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        Timeline(at(9, 0), at(9, 20), "UTC", OUTAGE_MORNING, (fault,))


def test_a_fault_on_a_stream_its_kind_cannot_reach_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot affect"):
        Fault(at(9, 5), at(9, 6), FaultKind.AW_DOWN, sources=(AX_TEXT_SOURCE,))


def test_a_pause_the_agent_cannot_see_is_refused() -> None:
    stretches = (*OUTAGE_MORNING[:1], Stretch(at(9, 10), at(9, 20), kind=StretchKind.ASLEEP))
    asleep_pause = Fault(at(9, 5), at(9, 15), FaultKind.PAUSED)
    timeline = Timeline(at(9, 0), at(9, 20), "UTC", stretches, (asleep_pause,))

    with pytest.raises(ValueError, match="pause edge"):
        SpoolRenderer().render(timeline, random.Random(0))
