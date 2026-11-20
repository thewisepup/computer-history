"""The true answers for a dataset, computed from its timeline and never from its database."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from computer_history.sources import WEB_SOURCE, WINDOW_SOURCE
from computer_history.store import Gap
from computer_history.synthetic.afk import reported_afk
from computer_history.synthetic.captures import Capture, agent_captures
from computer_history.synthetic.gaps import ExplainedGap, explained, unobserved
from computer_history.synthetic.generate import DatasetInputs
from computer_history.synthetic.renderer import RenderedSource
from computer_history.synthetic.timeline import (
    PRECISION,
    Timeline,
    local_midnight,
    observed_periods,
)
from computer_history.text import extract_domain

GENERATOR_VERSION = 3

Piece = tuple[datetime, datetime, str]


@dataclass(frozen=True)
class Totals:
    """Foreground and attended seconds per app, foreground seconds per domain, and AFK seconds."""

    foreground_app_seconds: Mapping[str, float]
    foreground_domain_seconds: Mapping[str, float]
    attended_app_seconds: Mapping[str, float]
    afk_seconds: float


@dataclass(frozen=True)
class CaptureCounts:
    """The capture agent's records by kind, and those naming one by trigger and by app."""

    kinds: Mapping[str, int]
    triggers: Mapping[str, int]
    apps: Mapping[str, int]


@dataclass(frozen=True)
class Manifest:
    """What a dataset holds: its inputs and range, time per local day and in total, counts and gaps.

    Time counts only what the sources record, so an ActivityWatch outage adds no time.
    """

    generator_version: int
    inputs: DatasetInputs | None
    start: datetime
    end: datetime
    timezone: str
    days: Mapping[str, Totals]
    total: Totals
    observations: Mapping[str, int]
    captures: CaptureCounts
    unobserved: Mapping[str, tuple[Gap, ...]]
    explained: tuple[ExplainedGap, ...]
    content_digest: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=_iso, indent=2, sort_keys=True) + "\n"


def true_answers(
    inputs: DatasetInputs | None,
    timeline: Timeline,
    rendered: Iterable[RenderedSource],
    content_digest: str,
) -> Manifest:
    """The manifest for a timeline, with the observation counts its rendered sources hold."""
    afk = reported_afk(timeline)
    records = agent_captures(timeline)
    seen = [s for period in observed_periods(timeline, WINDOW_SOURCE) for s in period]
    browsed = [s for period in observed_periods(timeline, WEB_SOURCE) for s in period]
    apps = [(s.start, s.end, s.app) for s in seen]
    domains = [
        (s.start, s.end, domain) for s in browsed if (domain := extract_domain(s.url)) is not None
    ]
    present = [(span.start, span.end) for span in afk if not span.afk]
    away = [(span.start, span.end, "afk") for span in afk if span.afk]
    series = (apps, domains, list(_intersect(apps, present)), away)
    days = _local_days(timeline)
    per_day = [_by_day(pieces, days) for pieces in series]
    whole = [("total", timeline.start, timeline.end)]
    total = [_by_day(pieces, whole)["total"] for pieces in series]
    counts: Counter[str] = Counter()
    for source in rendered:
        counts.update(source.observation_counts())
    return Manifest(
        generator_version=GENERATOR_VERSION,
        inputs=inputs,
        start=timeline.start,
        end=timeline.end,
        timezone=timeline.timezone,
        days={day: _totals(*(found[day] for found in per_day)) for day, _, _ in days},
        total=_totals(*total),
        observations=dict(sorted(counts.items())),
        captures=_captures(records),
        unobserved=unobserved(timeline, afk, records),
        explained=explained(timeline),
        content_digest=content_digest,
    )


def _captures(records: list[Capture]) -> CaptureCounts:
    kinds = Counter(record.kind for record in records)
    triggers = Counter(record.trigger for record in records if record.trigger is not None)
    apps = Counter(record.stretch.app for record in records if record.stretch is not None)
    return CaptureCounts(*(dict(sorted(found.items())) for found in (kinds, triggers, apps)))


def _totals(
    apps: Counter[str], domains: Counter[str], attended: Counter[str], afk: Counter[str]
) -> Totals:
    return Totals(_seconds(apps), _seconds(domains), _seconds(attended), afk["afk"] / 1000)


def _seconds(found: Counter[str]) -> dict[str, float]:
    return {key: ms / 1000 for key, ms in sorted(found.items())}


def _local_days(timeline: Timeline) -> list[tuple[str, datetime, datetime]]:
    zone = ZoneInfo(timeline.timezone)
    days = []
    day = timeline.start.astimezone(zone).date()
    while (start := local_midnight(day, zone)) < timeline.end:
        days.append((day.isoformat(), start, local_midnight(day + timedelta(days=1), zone)))
        day += timedelta(days=1)
    return days


def _by_day(
    pieces: Iterable[Piece], days: list[tuple[str, datetime, datetime]]
) -> dict[str, Counter[str]]:
    found: dict[str, Counter[str]] = {day: Counter() for day, _, _ in days}
    first = 0
    for start, end, key in pieces:
        while first < len(days) and days[first][2] <= start:
            first += 1
        for day, lo, hi in days[first:]:
            if lo >= end:
                break
            overlap = min(end, hi) - max(start, lo)
            if overlap > timedelta(0):
                found[day][key] += overlap // PRECISION
    return found


def _intersect(pieces: list[Piece], spans: list[tuple[datetime, datetime]]) -> Iterator[Piece]:
    index = 0
    for start, end, key in pieces:
        while index < len(spans) and spans[index][1] <= start:
            index += 1
        probe = index
        while probe < len(spans) and spans[probe][0] < end:
            lo, hi = max(start, spans[probe][0]), min(end, spans[probe][1])
            if hi > lo:
                yield lo, hi, key
            probe += 1


def _iso(value: object) -> str:
    if isinstance(value, date | datetime):
        return value.isoformat()
    raise TypeError(f"cannot write {value!r} to the manifest")
