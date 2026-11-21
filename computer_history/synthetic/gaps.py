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
    SLEPT_KIND,
    WINDOW_SOURCE,
    WINDOW_TEXT_SOURCE,
)
from computer_history.store import Gap
from computer_history.synthetic.afk import ReportedAfk
from computer_history.synthetic.captures import Capture
from computer_history.synthetic.spans import Span, intersect, merge, outside
from computer_history.synthetic.timeline import FaultKind, Timeline, observed_periods

SHORTEST_GAP = timedelta(seconds=1)
EXPLAINED_KINDS = {FaultKind.PAUSED: PAUSED_KIND, FaultKind.EXCLUDED: EXCLUDED_KIND}


@dataclass(frozen=True)
class ExplainedGap:
    """A stretch with no captured text that a record explains: a pause, an excluded app or sleep."""

    start: datetime
    end: datetime
    kind: str


def unobserved(
    timeline: Timeline, afk: Sequence[ReportedAfk], records: Sequence[Capture]
) -> Mapping[str, tuple[Gap, ...]]:
    """The stretches of a second or more each source records nothing for, by source.

    For captured text these are the attended stretches an outage or lost permission leaves
    with no record within the capture tolerance and no pause or sleep explaining them.
    """
    window = [(p[0].start, p[-1].end) for p in observed_periods(timeline, WINDOW_SOURCE)]
    present = merge((span.start, span.end) for span in afk if not span.afk)
    missed = _missed_by_agent(timeline, records, [start for start, _ in present])
    return {
        AFK_SOURCE: _gaps(outside([(s.start, s.end) for s in afk], timeline.start, timeline.end)),
        WINDOW_TEXT_SOURCE: _gaps(intersect(missed, present)),
        WINDOW_SOURCE: _gaps(outside(window, timeline.start, timeline.end)),
    }


def explained(
    timeline: Timeline, records: Sequence[Capture], afk: Sequence[ReportedAfk]
) -> tuple[ExplainedGap, ...]:
    """Each pause, excluded app's time in front and recorded sleep, oldest first.

    A sleep lasts until the next record or until the user is next present, whichever comes first.
    """
    starts = [start for start, _ in merge((s.start, s.end) for s in afk if not s.afk)]
    times = [record.at for record in records]
    faults = timeline.faults_of(*EXPLAINED_KINDS)
    gaps = [ExplainedGap(f.start, f.end, EXPLAINED_KINDS[f.kind]) for f in faults]
    for record in records:
        if record.kind == SLEPT_KIND:
            end = _silent_until(timeline, record, times, starts)
            gaps.append(ExplainedGap(record.at, end, SLEPT_KIND))
    return tuple(sorted(gaps, key=lambda gap: (gap.start, gap.end)))


def _missed_by_agent(
    timeline: Timeline, records: Sequence[Capture], starts: Sequence[datetime]
) -> list[Span]:
    times = [record.at for record in records]
    missed: list[Span] = []
    for fault in timeline.faults_of(FaultKind.AGENT_DOWN, FaultKind.PERMISSION_LOST):
        before = bisect_right(times, fault.start) - 1
        after = bisect_left(times, fault.end)
        edge = timeline.start
        for index in range(max(before, 0), after + 1):
            if index > before:
                end = timeline.end if index == len(times) else times[index] - CAPTURE_TOLERANCE
                if edge < end:
                    missed.append((edge, end))
            if index < len(times):
                edge = _explained_until(timeline, records[index], times, starts)
    return missed


def _explained_until(
    timeline: Timeline, record: Capture, times: Sequence[datetime], starts: Sequence[datetime]
) -> datetime:
    tolerance = record.at + CAPTURE_TOLERANCE
    if record.kind not in (PAUSED_KIND, SLEPT_KIND):
        return tolerance
    return max(tolerance, _silent_until(timeline, record, times, starts))


def _silent_until(
    timeline: Timeline, record: Capture, times: Sequence[datetime], starts: Sequence[datetime]
) -> datetime:
    later = bisect_right(times, record.at)
    until = times[later] if later < len(times) else timeline.end
    awake = bisect_right(starts, record.at)
    if record.kind == SLEPT_KIND and awake < len(starts):
        until = min(until, starts[awake])
    return until


def _gaps(spans: Iterable[Span]) -> tuple[Gap, ...]:
    return tuple(Gap(start, end) for start, end in spans if end - start >= SHORTEST_GAP)
