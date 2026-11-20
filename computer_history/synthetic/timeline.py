"""A source-neutral account of what happened on the Mac: stretches covering a range, plus faults."""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import Enum

DEFAULT_START = date(2026, 1, 5)
DEFAULT_TIMEZONE = "America/Los_Angeles"
PRECISION = timedelta(milliseconds=1)


class StretchKind(Enum):
    ACTIVE = "active"  # an app is in front, whether or not the user is there
    ASLEEP = "asleep"  # the Mac is asleep or locked, so no source records anything


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


def part_random(seed: int, part: str) -> random.Random:
    """A random generator for one part of the generator, fixed by the seed and the part's name."""
    digest = hashlib.sha256(f"{seed}:{part}".encode()).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))
