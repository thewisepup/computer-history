"""What happens to the user: each scenario places its happenings on the ordinary timeline."""

from __future__ import annotations

import random
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from computer_history.synthetic.timeline import (
    Fault,
    FaultKind,
    Stretch,
    StretchKind,
    Timeline,
    stretch_at,
)

Scenario = Callable[[Timeline, random.Random], Timeline]

EXCLUDED_APP = "1Password"
WORKDAY_CHECKS = (time(9, 30), time(17, 0))
OVERNIGHT_CHECK = time(23, 0)
OVERNIGHT_UNTIL = time(6, 0)


def typical(timeline: Timeline, rng: random.Random) -> Timeline:
    """An ordinary stretch of time with nothing going wrong."""
    return timeline


def messy(timeline: Timeline, rng: random.Random) -> Timeline:
    """Every fault kind, a midday sleep and an overnight AFK span, each on a fixed workday.

    The n-th happening goes on the range's n-th workday, wrapping round, so one day holds all.
    """
    zone = ZoneInfo(timeline.timezone)
    stretches = list(timeline.stretches)
    workdays = _workdays(stretches, timeline, zone)
    if not workdays:
        raise ValueError("the messy scenario needs a workday in the range")

    def on(index: int, at: time) -> datetime:
        day = workdays[index % len(workdays)]
        return datetime.combine(day, at, zone).astimezone(UTC)

    stretches = _overnight_afk(stretches, on(0, OVERNIGHT_CHECK), timeline, zone)
    nap = Stretch(on(1, time(12, 30)), on(1, time(12, 50)), kind=StretchKind.ASLEEP)
    stretches = _replace(stretches, nap)
    outage = _next_present(stretches, on(0, time(9, 45)))
    pause = _next_present(stretches, on(2, time(14, 50)))
    resume = _next_present(stretches, pause + timedelta(minutes=20))
    excluded_from = _next_present(stretches, max(on(3, time(16, 0)), resume))
    excluded_to = excluded_from + timedelta(minutes=10)
    app = Stretch(excluded_from, excluded_to, app=EXCLUDED_APP, title=EXCLUDED_APP)
    stretches = _replace(stretches, app)
    faults = (
        Fault(outage, _next_present(stretches, outage + timedelta(hours=2)), FaultKind.AW_DOWN),
        Fault(on(1, time(13, 40)), on(1, time(14, 10)), FaultKind.AGENT_DOWN),
        Fault(on(2, time(14, 15)), on(2, time(14, 35)), FaultKind.PERMISSION_LOST),
        Fault(pause, resume, FaultKind.PAUSED),
        Fault(excluded_from, excluded_to, FaultKind.EXCLUDED),
    )
    return replace(timeline, stretches=tuple(stretches), faults=timeline.faults + faults)


def _workdays(stretches: Sequence[Stretch], timeline: Timeline, zone: ZoneInfo) -> list[date]:
    days, day = [], timeline.start.astimezone(zone).date()
    while datetime.combine(day, time(), zone) < timeline.end:
        moments = [datetime.combine(day, at, zone) for at in WORKDAY_CHECKS]
        if all(timeline.start <= m < timeline.end for m in moments) and all(
            stretch_at(stretches, m).active for m in moments
        ):
            days.append(day)
        day += timedelta(days=1)
    return days


def _next_present(stretches: Sequence[Stretch], moment: datetime) -> datetime:
    index = max(0, bisect_right(stretches, moment, key=lambda s: s.start) - 1)
    for stretch in stretches[index:]:
        if stretch.active and not stretch.afk:
            return max(moment, stretch.start)
    raise ValueError(f"the user is never at the Mac after {moment}")


def _replace(stretches: list[Stretch], inserted: Stretch) -> list[Stretch]:
    start, end = inserted.start, inserted.end
    before = [replace(s, end=min(s.end, start)) for s in stretches if s.start < start]
    after = [replace(s, start=max(s.start, end)) for s in stretches if s.end > end]
    return [*before, inserted, *after]


def _overnight_afk(
    stretches: list[Stretch], check: datetime, timeline: Timeline, zone: ZoneInfo
) -> list[Stretch]:
    index = bisect_right(stretches, check, key=lambda s: s.start) - 1
    night = stretches[index]
    if night.active or index == 0 or not stretches[index - 1].active:
        raise ValueError(f"the Mac is not asleep after the day's work at {check}")
    next_day = check.astimezone(zone).date() + timedelta(days=1)
    morning = datetime.combine(next_day, OVERNIGHT_UNTIL, zone)
    until = min(night.end, morning.astimezone(UTC))
    away = replace(stretches[index - 1], start=night.start, end=until, afk=True)
    rest = [replace(night, start=until)] if until < night.end else []
    return [*stretches[:index], away, *rest, *stretches[index + 1 :]]


SCENARIOS: Mapping[str, Scenario] = MappingProxyType({"typical": typical, "messy": messy})
