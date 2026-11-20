"""Who the user is, as typed config: apps, sites, projects and a daily rhythm."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time


@dataclass(frozen=True)
class App:
    """An app the user works in, with window-title templates and the kind of work done there."""

    name: str
    titles: tuple[str, ...]
    weight: float = 1.0
    work_type: str = "coding"


@dataclass(frozen=True)
class Page:
    path: str
    title: str


@dataclass(frozen=True)
class Site:
    """A website the user visits in the browser, with page templates."""

    domain: str
    pages: tuple[Page, ...]
    weight: float = 1.0
    work_type: str = "research"
    scheme: str = "https"


@dataclass(frozen=True)
class Project:
    """An outcome the user works toward, with the apps, sites and files it uses."""

    name: str
    apps: tuple[str, ...]
    sites: tuple[str, ...]
    files: tuple[str, ...]
    weight: float = 1.0


@dataclass(frozen=True)
class Rhythm:
    """When the user works: the workday, lunch, breaks away from the Mac and evening sessions."""

    workday_start: time = time(9, 0)
    workday_end: time = time(17, 30)
    jitter_minutes: int = 20
    lunch_start: time = time(12, 15)
    lunch_minutes: int = 45
    breaks_every_minutes: int = 75
    break_minutes: tuple[int, int] = (5, 15)
    evening_chance: float = 0.3
    evening_start: time = time(20, 30)
    evening_minutes: int = 60
    weekend_workdays: bool = False


@dataclass(frozen=True)
class Persona:
    """Everything that makes one kind of user: their apps, sites, projects and daily rhythm.

    The browser names the app whose windows show sites, and interruptions break into any project.
    """

    name: str
    browser: str
    apps: tuple[App, ...]
    sites: tuple[Site, ...]
    projects: tuple[Project, ...]
    topics: tuple[str, ...]
    filler: tuple[str, ...]
    rhythm: Rhythm = field(default_factory=Rhythm)
    switch_seconds: float = 12.0
    focus_minutes: tuple[int, int] = (20, 50)
    interruptions: tuple[str, ...] = ()
    interruption_chance: float = 0.05
    meeting_app: str | None = None
    meeting_chance: float = 0.04
    meeting_minutes: tuple[int, int] = (25, 55)
    text_chars: tuple[int, int] = (200, 2000)
