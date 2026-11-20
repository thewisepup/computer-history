from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from itertools import product

import aw_watchers as watchers
from fake_aw import FakeAW

from computer_history.store import to_utc
from computer_history.synthetic import Stretch, StretchKind, Timeline
from computer_history.synthetic.activitywatch import (
    AFK_BUCKET,
    WEB_BUCKET,
    WINDOW_BUCKET,
    ActivityWatchRenderer,
)
from computer_history.synthetic.aw_api import AWEvent, ServedAW

DAY = datetime(2026, 1, 5, tzinfo=UTC)
MS = timedelta(milliseconds=1)
DOCS = "https://docs.python.org/3/library/sqlite3.html"


def at(hour: int, minute: int) -> datetime:
    return DAY + timedelta(hours=hour, minutes=minute)


def active(start: datetime, end: datetime, app: str, title: str, **fields) -> Stretch:
    return Stretch(start, end, app=app, title=title, **fields)


MORNING = Timeline(
    DAY,
    DAY + timedelta(days=1),
    "UTC",
    (
        Stretch(DAY, at(9, 0), kind=StretchKind.ASLEEP),
        active(at(9, 0), at(9, 10), "Cursor", "a.py"),
        active(at(9, 10), at(9, 12), "Cursor", "a.py"),
        active(at(9, 12), at(9, 15), "Google Chrome", "sqlite3", url=DOCS),
        active(at(9, 15), at(9, 25), "Google Chrome", "sqlite3", url=DOCS, afk=True),
        active(at(9, 25), at(9, 30), "Terminal", "zsh"),
        active(at(9, 30), at(9, 31), "Terminal", "zsh", afk=True),
        active(at(9, 31), at(9, 40), "Terminal", "zsh"),
        Stretch(at(9, 40), DAY + timedelta(days=1), kind=StretchKind.ASLEEP),
    ),
)


def served_spans(bucket: str, *keys: str) -> list[tuple[datetime, datetime, tuple]]:
    rendered = ActivityWatchRenderer().render(MORNING, random.Random(0))
    api = ServedAW(rendered.buckets, rendered.events)
    spans = []
    for raw in reversed(api.get_events(bucket)):
        start = to_utc(raw["timestamp"])
        end = start + timedelta(seconds=raw["duration"])
        spans.append((start, end, tuple(raw["data"][key] for key in keys)))
    return spans


def test_window_events_merge_runs_of_the_same_window_and_carry_on_while_away() -> None:
    assert served_spans(WINDOW_BUCKET, "app", "title") == [
        (at(9, 0), at(9, 12), ("Cursor", "a.py")),
        (at(9, 12), at(9, 25), ("Google Chrome", "sqlite3")),
        (at(9, 25), at(9, 40), ("Terminal", "zsh")),
    ]


def test_web_events_only_cover_the_browser_in_front() -> None:
    assert served_spans(WEB_BUCKET, "url", "title") == [(at(9, 12), at(9, 25), (DOCS, "sqlite3"))]


def test_afk_is_dated_from_the_last_input_and_short_absences_stay_present() -> None:
    assert served_spans(AFK_BUCKET, "status") == [
        (at(9, 0), at(9, 15), ("not-afk",)),
        (at(9, 15) + MS, at(9, 25), ("afk",)),
        (at(9, 25) + MS, at(9, 40), ("not-afk",)),
    ]


def test_served_events_match_the_test_fake_for_every_range_without_ties() -> None:
    fake = FakeAW({"bucket": "currentwindow"}, t0=DAY)
    raws = [
        fake.add("bucket", 0, 29.5, {"app": "a"}),
        fake.add("bucket", 0.5, 60, {"app": "b"}),
        fake.add("bucket", 2, 0.75, {"app": "c"}),
        fake.add("bucket", 5, 120, {"app": "d"}),
    ]
    events = tuple(
        AWEvent(
            raw["id"],
            to_utc(raw["timestamp"]),
            to_utc(raw["timestamp"]) + timedelta(seconds=raw["duration"]),
            raw["data"],
        )
        for raw in raws
    )
    served = ServedAW(fake.get_buckets(), {"bucket": events})
    edges = sorted({moment for event in events for moment in (event.start, event.end)})
    bounds = [None, *(edge + shift for edge in edges for shift in (-MS, timedelta(0), MS))]

    for start, end, limit in product(bounds, bounds, (-1, 0, 1, 2)):
        query = {"start": start, "end": end, "limit": limit}
        assert served.get_events("bucket", **query) == fake.get_events("bucket", **query), query
    for raw in raws:
        assert served.get_event("bucket", raw["id"]) == fake.get_event("bucket", raw["id"])
    assert served.get_event("bucket", 99) is None


WATCHED_DAY = watchers.Day(
    stretches=(
        watchers.Stretch("active", 600, "Cursor"),
        watchers.Stretch("idle", 300, "Cursor"),
        watchers.Stretch("active", 200, "Terminal"),
        watchers.Stretch("idle", 60, "Terminal"),
        watchers.Stretch("active", 100, "Terminal"),
        watchers.Stretch("asleep", 600, "Terminal"),
        watchers.Stretch("active", 300, "Cursor"),
    ),
    poll_phase=0,
    afk_phase=2,
)
AFK_POLL = timedelta(seconds=watchers.AFK_POLL_TIME)
SECOND = timedelta(seconds=1)


def watched_timeline(day: watchers.Day) -> Timeline:
    edge, stretches = watchers.T0, []
    for step in day.stretches:
        end = edge + timedelta(seconds=step.seconds)
        if step.kind == "asleep":
            stretches.append(Stretch(edge, end, kind=StretchKind.ASLEEP))
        else:
            stretches.append(
                Stretch(edge, end, app=step.app, title=step.app, afk=step.kind == "idle")
            )
        edge = end
    return Timeline(watchers.T0, edge, "UTC", tuple(stretches))


def spans(raws: list[dict]) -> list[tuple[datetime, datetime, dict]]:
    found = []
    for raw in sorted(raws, key=lambda raw: to_utc(raw["timestamp"])):
        start = to_utc(raw["timestamp"])
        found.append((start, start + timedelta(seconds=raw["duration"]), raw["data"]))
    return found


def simulated_and_rendered(bucket: str, simulated_bucket: str):
    simulated = watchers.HeartbeatAW()
    watchers.live_through(WATCHED_DAY, simulated, lambda now: None)
    rendered = ActivityWatchRenderer().render(watched_timeline(WATCHED_DAY), random.Random(0))
    served = ServedAW(rendered.buckets, rendered.events)
    return spans(simulated.events[simulated_bucket]), spans(served.get_events(bucket))


def test_window_events_match_the_watcher_except_for_its_last_one_second_poll() -> None:
    simulated, rendered = simulated_and_rendered(WINDOW_BUCKET, watchers.WINDOW_BUCKET)

    assert simulated == [(start, end - SECOND, data) for start, end, data in rendered]


def test_afk_spans_match_the_watcher_within_one_afk_poll() -> None:
    simulated, rendered = simulated_and_rendered(AFK_BUCKET, watchers.AFK_BUCKET)

    assert [data for _, _, data in simulated] == [data for _, _, data in rendered]
    for (sim_start, sim_end, data), (start, end, _) in zip(simulated, rendered, strict=True):
        if data["status"] == "afk":
            assert sim_start == start - SECOND, (sim_start, start)
        assert abs(sim_start - start) < AFK_POLL, (data, sim_start, start)
        assert abs(sim_end - end) < AFK_POLL, (data, sim_end, end)
