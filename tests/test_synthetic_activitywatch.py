from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from itertools import product

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
