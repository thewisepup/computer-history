"""The AFK spans aw-watcher-afk reports for a timeline, dated from the last input."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from itertools import groupby
from typing import NamedTuple

from computer_history.synthetic.timeline import Stretch, Timeline

AFK_TIMEOUT = timedelta(seconds=180)
WATCHER_STEP = timedelta(milliseconds=1)


class ReportedAfk(NamedTuple):
    start: datetime
    end: datetime
    afk: bool


def awake_periods(timeline: Timeline) -> Iterator[list[Stretch]]:
    """Each run of stretches with the Mac awake, in order."""
    for active, run in groupby(timeline.stretches, key=lambda stretch: stretch.active):
        if active:
            yield list(run)


def reported_afk(timeline: Timeline) -> list[ReportedAfk]:
    """The not-afk and afk spans the watcher reports, oldest first, and nothing while asleep.

    Away runs shorter than the timeout count as present, and each change of state starts a
    millisecond after the input that caused it, as the watcher dates them.
    """
    reported: list[ReportedAfk] = []
    for period in awake_periods(timeline):
        for afk, start, end in _states(period):
            after_afk = bool(reported) and reported[-1].afk and reported[-1].end == start
            nudged = afk or after_afk
            reported.append(ReportedAfk(start + WATCHER_STEP if nudged else start, end, afk))
    return reported


def _states(period: list[Stretch]) -> list[tuple[bool, datetime, datetime]]:
    states: list[tuple[bool, datetime, datetime]] = []
    for away, run in groupby(period, key=lambda stretch: stretch.afk):
        stretches = list(run)
        start, end = stretches[0].start, stretches[-1].end
        afk = away and end - start >= AFK_TIMEOUT
        if states and states[-1][0] == afk:
            start = states.pop()[1]
        states.append((afk, start, end))
    return states
