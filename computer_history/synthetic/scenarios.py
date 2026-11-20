"""What happens to the user: each scenario places its happenings on the ordinary timeline."""

from __future__ import annotations

import random
from bisect import bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType
from zoneinfo import ZoneInfo

from computer_history.synthetic.persona import Rhythm
from computer_history.synthetic.timeline import (
    Fault,
    FaultKind,
    Stretch,
    StretchKind,
    Timeline,
    stretch_at,
)

Scenario = Callable[[Timeline, Rhythm, random.Random], Timeline]

EXCLUDED_APP = "1Password"


def typical(timeline: Timeline, rhythm: Rhythm, rng: random.Random) -> Timeline:
    """An ordinary stretch of time with nothing going wrong."""
    return timeline


def messy(timeline: Timeline, rhythm: Rhythm, rng: random.Random) -> Timeline:
    """Every fault kind, a midday sleep and an overnight AFK span, each on a fixed workday.

    The n-th happening goes on the range's n-th workday, wrapping round, at a time the rhythm sets.
    """
    zone = ZoneInfo(timeline.timezone)
    stretches = list(timeline.stretches)
    start, end, lunch = rhythm.workday_start, rhythm.workday_end, rhythm.lunch_start
    back = _after(lunch, rhythm.lunch_minutes)
    workdays = _workdays(stretches, timeline, zone, (_after(start, 30), _after(end, -30)))
    if not workdays:
        raise ValueError("the messy scenario needs a workday in the range")

    def on(index: int, at: time) -> datetime:
        day = workdays[index % len(workdays)]
        return datetime.combine(day, at, zone).astimezone(UTC)

    overnight = on(0, _after(rhythm.evening_start, rhythm.evening_minutes + 90))
    stretches = _overnight_afk(stretches, overnight, _after(start, -180), zone)
    nap = Stretch(on(1, _after(lunch, 15)), on(1, _after(lunch, 35)), kind=StretchKind.ASLEEP)
    stretches = _replace(stretches, nap)
    outage = _next_present(stretches, on(0, _after(start, 45)))
    pause = _next_present(stretches, on(2, _after(back, 110)))
    resume = _next_present(stretches, pause + timedelta(minutes=20))
    excluded_from = _next_present(stretches, max(on(3, _after(end, -90)), resume))
    excluded_to = excluded_from + timedelta(minutes=10)
    app = Stretch(excluded_from, excluded_to, app=EXCLUDED_APP, title=EXCLUDED_APP)
    stretches = _replace(stretches, app)
    faults = (
        Fault(outage, _next_present(stretches, outage + timedelta(hours=2)), FaultKind.AW_DOWN),
        Fault(on(1, _after(back, 40)), on(1, _after(back, 70)), FaultKind.AGENT_DOWN),
        Fault(on(2, _after(back, 75)), on(2, _after(back, 95)), FaultKind.PERMISSION_LOST),
        Fault(pause, resume, FaultKind.PAUSED),
        Fault(excluded_from, excluded_to, FaultKind.EXCLUDED),
    )
    return replace(timeline, stretches=tuple(stretches), faults=timeline.faults + faults)


def _after(at: time, minutes: int) -> time:
    return (datetime.combine(date(2000, 1, 2), at) + timedelta(minutes=minutes)).time()


def _workdays(
    stretches: Sequence[Stretch], timeline: Timeline, zone: ZoneInfo, checks: Sequence[time]
) -> list[date]:
    days, day = [], timeline.start.astimezone(zone).date()
    while datetime.combine(day, time(), zone) < timeline.end:
        moments = [datetime.combine(day, at, zone) for at in checks]
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
    stretches: list[Stretch], check: datetime, morning_at: time, zone: ZoneInfo
) -> list[Stretch]:
    index = bisect_right(stretches, check, key=lambda s: s.start) - 1
    night = stretches[index]
    if night.active or index == 0 or not stretches[index - 1].active:
        raise ValueError(f"the Mac is not asleep after the day's work at {check}")
    next_day = check.astimezone(zone).date() + timedelta(days=1)
    morning = datetime.combine(next_day, morning_at, zone)
    until = min(night.end, morning.astimezone(UTC))
    away = replace(stretches[index - 1], start=night.start, end=until, afk=True)
    rest = [replace(night, start=until)] if until < night.end else []
    return [*stretches[:index], away, *rest, *stretches[index + 1 :]]


SCENARIOS: Mapping[str, Scenario] = MappingProxyType({"typical": typical, "messy": messy})
