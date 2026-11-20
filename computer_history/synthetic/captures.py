"""When the capture agent writes a capture for a timeline, as its capture schedule decides."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import NamedTuple

from computer_history.synthetic.timeline import PRECISION, Stretch, Timeline

HEARTBEAT = timedelta(seconds=30)
SETTLE = timedelta(seconds=1)
MINIMUM_GAP = timedelta(seconds=1)
IDLE_THRESHOLD = timedelta(seconds=180)
PRECEDENCE = ("app", "window", "title")

Focus = tuple[str, str | None, str]


class Capture(NamedTuple):
    at: datetime
    trigger: str
    stretch: Stretch


def agent_captures(timeline: Timeline) -> list[Capture]:
    """The captures the agent writes, oldest first, for an agent running from the range start.

    A focus change captures once it settles, and a heartbeat follows the last capture while
    the user is present.
    """
    captures: list[Capture] = []
    pending: str | None = None
    pending_since = settled_at = heartbeat_due = timeline.start
    last: datetime | None = None
    seen: Focus | None = None
    silent = True
    for start, end, stretch in _listening(timeline):
        if stretch is None:
            pending, silent = None, True
            continue
        if silent:
            heartbeat_due, silent = start + SETTLE, False
        focus = (stretch.app, stretch.project, stretch.title)
        change = _change(seen, focus)
        seen = focus
        if change is not None:
            if pending is None:
                pending, pending_since = change, start
            else:
                pending = next(kind for kind in PRECEDENCE if kind in (pending, change))
            settled_at = start + SETTLE
        while True:
            if pending is None:
                due, trigger = heartbeat_due, "heartbeat"
            else:
                due, trigger = min(settled_at, pending_since + HEARTBEAT), pending
            if last is not None:
                due = max(due, last + MINIMUM_GAP)
            if due >= end:
                break
            captures.append(Capture(due, trigger, stretch))
            pending, last, heartbeat_due = None, due, due + HEARTBEAT
    return captures


def _change(seen: Focus | None, focus: Focus) -> str | None:
    if seen is None or seen == focus:
        return None
    if seen[0] != focus[0]:
        return "app"
    return "window" if seen[1] != focus[1] else "title"


def _listening(timeline: Timeline) -> Iterator[tuple[datetime, datetime, Stretch | None]]:
    away_since: datetime | None = None
    for stretch in timeline.stretches:
        if not stretch.active:
            away_since = None
            yield stretch.start, stretch.end, None
            continue
        if not stretch.afk:
            away_since = None
            yield stretch.start, stretch.end, stretch
            continue
        away_since = away_since or stretch.start
        idle = away_since + IDLE_THRESHOLD + PRECISION
        if stretch.start < idle:
            yield stretch.start, min(stretch.end, idle), stretch
        if idle < stretch.end:
            yield max(stretch.start, idle), stretch.end, None
