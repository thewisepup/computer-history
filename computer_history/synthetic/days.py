"""The ordinary days a persona lives through, as stretches from midnight to midnight."""

from __future__ import annotations

import random
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import TypeVar
from zoneinfo import ZoneInfo

from computer_history.synthetic.persona import App, Persona
from computer_history.synthetic.timeline import Stretch, StretchKind, local_midnight

T = TypeVar("T")

MIN_WORK_MINUTES = 1.0


def live(
    persona: Persona, first_day: date, days: int, timezone: str, rng: random.Random
) -> tuple[Stretch, ...]:
    """The persona's ordinary stretches from local midnight of the first day, for the given days."""
    zone = ZoneInfo(timezone)
    life = _Life(persona, rng, local_midnight(first_day, zone))
    for offset in range(days):
        day = first_day + timedelta(days=offset)
        if day.weekday() < 5 or persona.rhythm.weekend_workdays:
            life.workday(day, zone)
    life.sleep_until(local_midnight(first_day + timedelta(days=days), zone))
    return tuple(life.stretches)


class _Life:
    def __init__(self, persona: Persona, rng: random.Random, start: datetime) -> None:
        self.persona = persona
        self.rng = rng
        self.cursor = start
        self.stretches: list[Stretch] = []
        self.focus_end = start
        self.project = persona.projects[0]
        self.values: dict[str, str] = {}
        self.texts: dict[tuple[str, str], str] = {}
        self.apps = {app.name: app for app in persona.apps}
        self.sites = {site.domain: site for site in persona.sites}

    def workday(self, day: date, zone: ZoneInfo) -> None:
        rhythm = self.persona.rhythm
        midnight = local_midnight(day + timedelta(days=1), zone)
        start = self._at(day, rhythm.workday_start, zone, rhythm.jitter_minutes)
        end = min(self._at(day, rhythm.workday_end, zone, rhythm.jitter_minutes), midnight)
        lunch = self._at(day, rhythm.lunch_start, zone, rhythm.jitter_minutes // 2)
        back = lunch + self._minutes(rhythm.lunch_minutes - 10, rhythm.lunch_minutes + 10)
        self.sleep_until(start)
        self.focus_end = start
        self.work_with_breaks(lunch)
        self.away_until(back)
        self.work_with_breaks(end)
        if self.rng.random() < rhythm.evening_chance:
            evening = self._at(day, rhythm.evening_start, zone, rhythm.jitter_minutes)
            self.sleep_until(evening)
            self.focus_end = evening
            minutes = rhythm.evening_minutes
            finish = evening + self._minutes(minutes - 15, minutes + 15)
            self.work_with_breaks(min(finish, midnight))

    def work_with_breaks(self, until: datetime) -> None:
        rhythm = self.persona.rhythm
        longest = timedelta(minutes=rhythm.break_minutes[1])
        while True:
            minutes = self.rng.expovariate(1 / rhythm.breaks_every_minutes)
            gap = timedelta(minutes=max(MIN_WORK_MINUTES, minutes))
            pause = self._ms(self.cursor + gap)
            if pause + longest >= until:
                self.work_until(until)
                return
            self.work_until(pause)
            self.away_until(pause + self._minutes(*rhythm.break_minutes))

    def work_until(self, until: datetime) -> None:
        while self.cursor < until:
            if self.cursor >= self.focus_end:
                self._new_focus(until)
                continue
            seconds = max(1.0, self.rng.expovariate(1 / self.persona.switch_seconds))
            end = min(self._ms(self.cursor + timedelta(seconds=seconds)), self.focus_end, until)
            self._do(end)

    def away_until(self, until: datetime) -> None:
        if until <= self.cursor:
            return
        if not self.stretches or not self.stretches[-1].active:
            self.sleep_until(until)
            return
        last = self.stretches[-1]
        self._append(
            Stretch(
                self.cursor,
                until,
                app=last.app,
                title=last.title,
                url=last.url,
                text=last.text,
                project=last.project,
                work_type=last.work_type,
                afk=True,
            )
        )

    def sleep_until(self, until: datetime) -> None:
        if until > self.cursor:
            self._append(Stretch(self.cursor, until, kind=StretchKind.ASLEEP))

    def _new_focus(self, until: datetime) -> None:
        persona, rng = self.persona, self.rng
        self.project = _pick(rng, persona.projects, [p.weight for p in persona.projects])
        self.values = {
            "project": self.project.name,
            "file": rng.choice(self.project.files),
            "topic": rng.choice(persona.topics),
            "n": str(rng.randint(2, 480)),
        }
        if persona.meeting_app is not None and rng.random() < persona.meeting_chance:
            self.focus_end = min(self.cursor + self._minutes(*persona.meeting_minutes), until)
            meeting = self.apps[persona.meeting_app]
            self._append(self._stretch(self.focus_end, meeting, rng.choice(meeting.titles)))
            return
        self.focus_end = self.cursor + self._minutes(*persona.focus_minutes)

    def _do(self, end: datetime) -> None:
        persona, rng = self.persona, self.rng
        if persona.interruptions and rng.random() < persona.interruption_chance:
            app = self.apps[rng.choice(persona.interruptions)]
            self._append(self._stretch(end, app, rng.choice(app.titles), in_project=False))
            return
        apps = [self.apps[name] for name in self.project.apps]
        app = _pick(rng, apps, [a.weight for a in apps])
        if app.name != persona.browser:
            self._append(self._stretch(end, app, rng.choice(app.titles)))
            return
        sites = [self.sites[domain] for domain in self.project.sites]
        site = _pick(rng, sites, [s.weight for s in sites])
        page = rng.choice(site.pages)
        url = f"{site.scheme}://{site.domain}{page.path.format(**self.values)}"
        self._append(self._stretch(end, app, page.title, url=url, work_type=site.work_type))

    def _stretch(
        self,
        end: datetime,
        app: App,
        template: str,
        *,
        url: str | None = None,
        work_type: str | None = None,
        in_project: bool = True,
    ) -> Stretch:
        title = template.format(**self.values)
        return Stretch(
            self.cursor,
            end,
            app=app.name,
            title=title,
            url=url,
            text=self._text(app.name, title),
            project=self.project.name if in_project else None,
            work_type=work_type or app.work_type,
        )

    def _text(self, app: str, title: str) -> str:
        key = (app, title)
        if key not in self.texts:
            low, high = self.persona.text_chars
            size = self.rng.randint(low, high)
            parts = [title]
            while sum(len(part) + 1 for part in parts) < size:
                parts.append(self.rng.choice(self.persona.filler).format(**self.values))
            self.texts[key] = "\n".join(parts)[:size]
        return self.texts[key]

    def _append(self, stretch: Stretch) -> None:
        self.stretches.append(stretch)
        self.cursor = stretch.end

    def _at(self, day: date, at: time, zone: ZoneInfo, jitter: int) -> datetime:
        base = datetime.combine(day, at, zone).astimezone(UTC)
        return max(self.cursor, base + self._minutes(-jitter, jitter))

    def _minutes(self, low: float, high: float) -> timedelta:
        return timedelta(milliseconds=round(self.rng.uniform(low, high) * 60_000))

    @staticmethod
    def _ms(moment: datetime) -> datetime:
        return moment.replace(microsecond=moment.microsecond // 1000 * 1000)


def _pick(rng: random.Random, items: Sequence[T], weights: Sequence[float]) -> T:
    return rng.choices(items, weights=weights)[0]
