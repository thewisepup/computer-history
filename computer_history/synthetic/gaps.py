"""The gaps a dataset's sources leave: unobserved stretches per source, and explained gaps."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from computer_history.sources import (
    AFK_SOURCE,
    CAPTURE_TOLERANCE,
    EXCLUDED_KIND,
    PAUSED_KIND,
    WINDOW_SOURCE,
    WINDOW_TEXT_SOURCE,
)
from computer_history.store import Gap
from computer_history.synthetic.afk import ReportedAfk
from computer_history.synthetic.captures import Capture
from computer_history.synthetic.spans import Span, intersect, outside
from computer_history.synthetic.timeline import FaultKind, Timeline, observed_periods

SHORTEST_GAP = timedelta(seconds=1)
EXPLAINED_KINDS = {FaultKind.PAUSED: PAUSED_KIND, FaultKind.EXCLUDED: EXCLUDED_KIND}


@dataclass(frozen=True)
class ExplainedGap:
    """A stretch with no captured text that a record explains: a pause or an excluded app."""

    start: datetime
    end: datetime
    kind: str


def unobserved(
    timeline: Timeline, afk: Sequence[ReportedAfk], records: Sequence[Capture]
) -> Mapping[str, tuple[Gap, ...]]:
    """The stretches of a second or more each source records nothing for, by source.

    For captured text these are the attended stretches an outage or lost permission leaves
    with no record within the capture tolerance.
    """
    window = [(p[0].start, p[-1].end) for p in observed_periods(timeline, WINDOW_SOURCE)]
    present = [(span.start, span.end) for span in afk if not span.afk]
    return {
        AFK_SOURCE: _gaps(outside([(s.start, s.end) for s in afk], timeline.start, timeline.end)),
        WINDOW_TEXT_SOURCE: _gaps(intersect(_missed_by_agent(timeline, records), present)),
        WINDOW_SOURCE: _gaps(outside(window, timeline.start, timeline.end)),
    }


def explained(timeline: Timeline) -> tuple[ExplainedGap, ...]:
    """Each pause and each excluded app's time in front, oldest first."""
    faults = timeline.faults_of(*EXPLAINED_KINDS)
    return tuple(ExplainedGap(f.start, f.end, EXPLAINED_KINDS[f.kind]) for f in faults)


def _missed_by_agent(timeline: Timeline, records: Sequence[Capture]) -> list[Span]:
    times = [record.at for record in records]
    missed: list[Span] = []
    for fault in timeline.faults_of(FaultKind.AGENT_DOWN, FaultKind.PERMISSION_LOST):
        before = bisect_right(times, fault.start) - 1
        after = bisect_left(times, fault.end)
        start = timeline.start if before < 0 else times[before] + CAPTURE_TOLERANCE
        end = timeline.end if after == len(times) else times[after] - CAPTURE_TOLERANCE
        missed.append((start, end))
    return missed


def _gaps(spans: Iterable[Span]) -> tuple[Gap, ...]:
    return tuple(Gap(start, end) for start, end in spans if end - start >= SHORTEST_GAP)
