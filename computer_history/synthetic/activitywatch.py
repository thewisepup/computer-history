"""The ActivityWatch renderer: window, AFK and web buckets as the watchers leave them."""

from __future__ import annotations

import random
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from itertools import groupby
from pathlib import Path
from typing import Any

from computer_history.sources import (
    AFK_SOURCE,
    WEB_SOURCE,
    WINDOW_SOURCE,
    ActivityWatch,
)
from computer_history.synthetic.afk import awake_periods, reported_afk
from computer_history.synthetic.aw_api import AWEvent, ServedAW
from computer_history.synthetic.renderer import Feed
from computer_history.synthetic.timeline import Stretch, Timeline

HOST = "synthetic-mac.local"
WINDOW_BUCKET = f"aw-watcher-window_{HOST}"
AFK_BUCKET = f"aw-watcher-afk_{HOST}"
WEB_BUCKET = f"aw-watcher-web-chrome_{HOST}"
BUCKETS = {
    WINDOW_BUCKET: ("currentwindow", "aw-watcher-window", WINDOW_SOURCE),
    AFK_BUCKET: ("afkstatus", "aw-watcher-afk", AFK_SOURCE),
    WEB_BUCKET: ("web.tab.current", "aw-client-web", WEB_SOURCE),
}

Span = tuple[datetime, datetime, Mapping[str, Any]]


@dataclass(frozen=True)
class RenderedActivityWatch:
    """The buckets ActivityWatch would list and the events each holds, oldest first."""

    buckets: Mapping[str, Mapping[str, Any]]
    events: Mapping[str, tuple[AWEvent, ...]]

    def observation_counts(self) -> Mapping[str, int]:
        return {BUCKETS[bucket][2]: len(found) for bucket, found in self.events.items()}

    def feed(self, folder: Path) -> Feed:
        adapter = ActivityWatch(ServedAW(self.buckets, self.events))
        return Feed(adapter, adapter)


class ActivityWatchRenderer:
    name = "activitywatch"
    streams = (WINDOW_SOURCE, AFK_SOURCE, WEB_SOURCE)

    def render(self, timeline: Timeline, rng: random.Random) -> RenderedActivityWatch:
        """Merged window and web events per run of identical data, and AFK dated from input."""
        if timeline.faults:
            raise ValueError("the ActivityWatch renderer does not render faults yet")
        window: list[Span] = []
        web: list[Span] = []
        for period in awake_periods(timeline):
            window += _runs(period, lambda s: {"app": s.app, "title": s.title})
            web += _runs(period, lambda s: s.url and {"url": s.url, "title": s.title})
        web = [(start, end, {**data, **_tab(rng)}) for start, end, data in web]
        afk = [
            (span.start, span.end, {"status": "afk" if span.afk else "not-afk"})
            for span in reported_afk(timeline)
        ]
        events = {
            WINDOW_BUCKET: _events(window),
            AFK_BUCKET: _events(afk),
            WEB_BUCKET: _events(web),
        }
        created = timeline.start.isoformat()
        buckets = {
            bucket: {
                "id": bucket,
                "created": created,
                "type": bucket_type,
                "client": client,
                "hostname": HOST,
                "data": {},
            }
            for bucket, (bucket_type, client, _) in BUCKETS.items()
        }
        return RenderedActivityWatch(buckets, events)


def _runs(
    period: Iterable[Stretch], data: Callable[[Stretch], Mapping[str, Any] | None]
) -> list[Span]:
    runs = []
    for value, run in groupby(period, key=data):
        stretches = list(run)
        if value:
            runs.append((stretches[0].start, stretches[-1].end, value))
    return runs


def _tab(rng: random.Random) -> dict[str, Any]:
    return {"audible": False, "incognito": False, "tabCount": rng.randint(3, 40)}


def _events(spans: Iterable[Span]) -> tuple[AWEvent, ...]:
    return tuple(
        AWEvent(index, start, end, data) for index, (start, end, data) in enumerate(spans, 1)
    )
