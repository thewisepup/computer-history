"""A source-neutral account of what happened on the Mac: stretches covering a range, plus faults."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from itertools import groupby
from zoneinfo import ZoneInfo

from computer_history.sources import AFK_SOURCE, WEB_SOURCE, WINDOW_SOURCE, WINDOW_TEXT_SOURCE

PRECISION = timedelta(milliseconds=1)


class StretchKind(Enum):
    ACTIVE = "active"  # an app is in front, whether or not the user is there
    ASLEEP = "asleep"  # the Mac is asleep


@dataclass(frozen=True)
class Stretch:
    """A span of time with one app and window in front, or the Mac asleep.

    A url means the app is a browser showing that page, and afk means the user is away.
    """

    start: datetime
    end: datetime
    kind: StretchKind = StretchKind.ACTIVE
    app: str = ""
    title: str = ""
    url: str | None = None
    text: str = ""
    project: str | None = None
    work_type: str | None = None
    afk: bool = False

    @property
    def active(self) -> bool:
        return self.kind is StretchKind.ACTIVE


class FaultKind(Enum):
    AW_DOWN = "activitywatch down"
    AGENT_DOWN = "capture agent down"
    PERMISSION_LOST = "accessibility permission lost"
    PAUSED = "capture paused"
    EXCLUDED = "app excluded"  # the app in front is denylisted


AFFECTED_STREAMS: dict[FaultKind, tuple[str, ...]] = {
    FaultKind.AW_DOWN: (WINDOW_SOURCE, AFK_SOURCE, WEB_SOURCE),
    FaultKind.AGENT_DOWN: (WINDOW_TEXT_SOURCE,),
    FaultKind.PERMISSION_LOST: (WINDOW_TEXT_SOURCE,),
    FaultKind.PAUSED: (WINDOW_TEXT_SOURCE,),
    FaultKind.EXCLUDED: (WINDOW_TEXT_SOURCE,),
}


AGENT_FAULTS = (
    FaultKind.AGENT_DOWN,
    FaultKind.PERMISSION_LOST,
    FaultKind.PAUSED,
    FaultKind.EXCLUDED,
)


@dataclass(frozen=True)
class Fault:
    """Something going wrong with one or more sources over a span of time."""

    start: datetime
    end: datetime
    kind: FaultKind
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        unknown = set(self.sources) - set(AFFECTED_STREAMS[self.kind])
        if unknown:
            raise ValueError(f"a {self.kind.value} fault cannot affect {sorted(unknown)}")

    @property
    def streams(self) -> tuple[str, ...]:
        return self.sources or AFFECTED_STREAMS[self.kind]


@dataclass(frozen=True)
class Timeline:
    """Ordered stretches exactly covering the range from start to end, and the faults over them."""

    start: datetime
    end: datetime
    timezone: str
    stretches: tuple[Stretch, ...]
    faults: tuple[Fault, ...] = ()

    def __post_init__(self) -> None:
        edge = self.start
        for stretch in self.stretches:
            if stretch.start != edge or stretch.end <= stretch.start:
                raise ValueError(f"stretch {stretch.start}..{stretch.end} does not follow {edge}")
            edge = stretch.end
        if edge != self.end:
            raise ValueError(f"stretches end at {edge}, not at the range end {self.end}")
        for fault in self.faults:
            if not self.start <= fault.start < fault.end <= self.end:
                raise ValueError(f"fault {fault.start}..{fault.end} is not inside the range")
        agent = self.faults_of(*AGENT_FAULTS)
        for earlier, later in zip(agent, agent[1:], strict=False):
            if later.start < earlier.end:
                raise ValueError(f"capture agent faults overlap at {later.start}")
        edges = (f for fault in self.faults for f in (fault.start, fault.end))
        for moment in (self.start, self.end, *(s.start for s in self.stretches), *edges):
            if moment.tzinfo is not UTC or moment.microsecond % 1000:
                raise ValueError(f"{moment!r} is not a UTC time to the millisecond")

    def faults_of(self, *kinds: FaultKind, stream: str | None = None) -> list[Fault]:
        """The faults of the given kinds, affecting the stream if one is given, oldest first."""
        return sorted(
            (f for f in self.faults if f.kind in kinds and (stream is None or stream in f.streams)),
            key=lambda fault: (fault.start, fault.end),
        )


def stretch_at(stretches: Sequence[Stretch], moment: datetime) -> Stretch:
    """The stretch the moment falls in, or the first one for a moment before them all."""
    return stretches[max(0, bisect_right(stretches, moment, key=lambda s: s.start) - 1)]


def observed_periods(timeline: Timeline, stream: str) -> Iterator[list[Stretch]]:
    """Each run of awake stretches an ActivityWatch stream records, cut where it is down."""
    down = timeline.faults_of(FaultKind.AW_DOWN, stream=stream)
    pieces = fault_pieces(timeline.stretches, down)
    for observed, run in groupby(pieces, key=lambda piece: piece[0].active and not piece[1]):
        if observed:
            yield [stretch for stretch, _ in run]


def fault_pieces(
    stretches: Sequence[Stretch], faults: Sequence[Fault]
) -> Iterator[tuple[Stretch, tuple[Fault, ...]]]:
    """The stretches cut at every fault edge, each piece with the faults over it."""
    edges = sorted({moment for fault in faults for moment in (fault.start, fault.end)})
    index = 0
    for stretch in stretches:
        start = stretch.start
        while index < len(edges) and edges[index] <= start:
            index += 1
        while start < stretch.end:
            end = stretch.end
            if index < len(edges) and edges[index] < end:
                end = edges[index]
                index += 1
            whole = (start, end) == (stretch.start, stretch.end)
            piece = stretch if whole else replace(stretch, start=start, end=end)
            yield piece, tuple(f for f in faults if f.start <= start < f.end)
            start = end


def local_midnight(day: date, zone: ZoneInfo) -> datetime:
    """The UTC time at which the day begins in the zone."""
    return datetime.combine(day, time(), zone).astimezone(UTC)
