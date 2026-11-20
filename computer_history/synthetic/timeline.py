"""A source-neutral account of what happened on the Mac: stretches covering a range, plus faults."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import Enum
from itertools import groupby
from zoneinfo import ZoneInfo

PRECISION = timedelta(milliseconds=1)


class StretchKind(Enum):
    ACTIVE = "active"  # an app is in front, whether or not the user is there
    ASLEEP = "asleep"  # the Mac is asleep or locked


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
    EXCLUDED = "app excluded"


@dataclass(frozen=True)
class Fault:
    """Something going wrong with one or more sources over a span of time."""

    start: datetime
    end: datetime
    kind: FaultKind
    sources: tuple[str, ...] = ()


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
        for moment in (self.start, self.end, *(s.start for s in self.stretches)):
            if moment.tzinfo is not UTC or moment.microsecond % 1000:
                raise ValueError(f"{moment!r} is not a UTC time to the millisecond")


def awake_periods(timeline: Timeline) -> Iterator[list[Stretch]]:
    """Each run of stretches with the Mac awake, in order."""
    for active, run in groupby(timeline.stretches, key=lambda stretch: stretch.active):
        if active:
            yield list(run)


def local_midnight(day: date, zone: ZoneInfo) -> datetime:
    """The UTC time at which the day begins in the zone."""
    return datetime.combine(day, time(), zone).astimezone(UTC)
