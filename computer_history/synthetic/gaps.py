"""The gaps a dataset's sources leave: unobserved stretches per source, and explained gaps."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from computer_history.sources import (
    AFK_SOURCE,
    AX_TEXT_SOURCE,
    CAPTURE_TOLERANCE,
    WINDOW_SOURCE,
)
from computer_history.store import Gap
from computer_history.synthetic.afk import ReportedAfk
from computer_history.synthetic.captures import Capture
from computer_history.synthetic.timeline import FaultKind, Timeline, observed_periods

MIN_GAP = timedelta(seconds=1)
EXPLAINED_KINDS = {FaultKind.PAUSED: "paused", FaultKind.EXCLUDED: "excluded"}

Span = tuple[datetime, datetime]


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
        AFK_SOURCE: _gaps(_outside(timeline, [(s.start, s.end) for s in afk])),
        AX_TEXT_SOURCE: _gaps(_intersect(_missed_by_agent(timeline, records), present)),
        WINDOW_SOURCE: _gaps(_outside(timeline, window)),
    }


def explained(timeline: Timeline) -> tuple[ExplainedGap, ...]:
    """Each pause and each excluded app's time in front, oldest first."""
    faults = timeline.faults_of(*EXPLAINED_KINDS)
    return tuple(ExplainedGap(f.start, f.end, EXPLAINED_KINDS[f.kind]) for f in faults)


def _missed_by_agent(timeline: Timeline, records: Sequence[Capture]) -> list[Span]:
    times = [record.at for record in records]
    missed = []
    for fault in timeline.faults_of(FaultKind.AGENT_DOWN, FaultKind.PERMISSION_LOST):
        before = bisect_right(times, fault.start) - 1
        after = bisect_left(times, fault.end)
        start = timeline.start if before < 0 else times[before] + CAPTURE_TOLERANCE
        end = timeline.end if after == len(times) else times[after] - CAPTURE_TOLERANCE
        missed.append((start, end))
    return missed


def _outside(timeline: Timeline, covered: Iterable[Span]) -> list[Span]:
    outside, edge = [], timeline.start
    for start, end in sorted(covered):
        if start > edge:
            outside.append((edge, start))
        edge = max(edge, end)
    if edge < timeline.end:
        outside.append((edge, timeline.end))
    return outside


def _intersect(spans: Iterable[Span], within: Sequence[Span]) -> list[Span]:
    found: list[Span] = []
    for start, end in sorted(spans):
        for lo, hi in within:
            lo, hi = max(start, lo), min(end, hi)
            if lo >= hi:
                continue
            if found and lo <= found[-1][1]:
                found[-1] = (found[-1][0], max(found[-1][1], hi))
            else:
                found.append((lo, hi))
    return found


def _gaps(spans: Iterable[Span]) -> tuple[Gap, ...]:
    return tuple(Gap(start, end) for start, end in spans if end - start >= MIN_GAP)
