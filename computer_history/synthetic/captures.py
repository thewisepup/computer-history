"""The records the capture agent writes for a timeline, as its capture schedule decides."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from enum import Enum
from typing import NamedTuple

from computer_history.sources.capture_spool import (
    CAPTURE_KIND,
    EXCLUDED_KIND,
    HEARTBEAT_SECONDS,
    PAUSED_KIND,
    RESUMED_KIND,
    SLEPT_KIND,
    WOKE_KIND,
)
from computer_history.synthetic.spans import merge
from computer_history.synthetic.timeline import (
    AGENT_FAULTS,
    PRECISION,
    FaultKind,
    Stretch,
    Timeline,
    fault_pieces,
    stretch_at,
)

HEARTBEAT = timedelta(seconds=HEARTBEAT_SECONDS)
SETTLE = timedelta(seconds=1)
POLL = timedelta(milliseconds=500)
RECORD_SPACING = timedelta(seconds=1)
IDLE_THRESHOLD = timedelta(seconds=180)
PRECEDENCE = ("app", "window", "title")

Focus = tuple[str, str | None, str]


class Mode(Enum):
    LISTENING = "listening"
    SILENT = "silent"  # asleep or idle
    PAUSED = "paused"  # silent, and focus is next polled a tick after the resume
    DOWN = "down"
    BLIND = "blind"  # no Accessibility permission
    EXCLUDED = "excluded"


class Capture(NamedTuple):
    at: datetime
    trigger: str | None
    stretch: Stretch | None
    kind: str = CAPTURE_KIND


def agent_captures(timeline: Timeline) -> list[Capture]:
    """The records the agent writes, oldest first, for an agent running from the range start.

    A focus change captures once it settles, a heartbeat follows the last capture while the user
    is present, and the Mac falling asleep and waking write slept and woke records.
    """
    captures: list[Capture] = []
    pending: str | None = None
    pending_since = settled_at = heartbeat_due = timeline.start
    last: datetime | None = None
    seen: Focus | None = None
    silent = True
    resumed_at: datetime | None = None
    for start, end, stretch, mode in _listening(timeline):
        if mode is Mode.DOWN:
            pending, silent, seen, last, resumed_at = None, True, None, None, None
            continue
        if stretch is None or mode in (Mode.SILENT, Mode.PAUSED):
            pending, silent = None, True
            resumed_at = end if mode is Mode.PAUSED else None
            continue
        if silent:
            heartbeat_due, silent = start + SETTLE, False
        excluded = mode is Mode.EXCLUDED
        focus: Focus = (stretch.app, None, "")
        if not excluded:
            focus = (stretch.app, stretch.project, stretch.title)
        change = _change(seen, focus)
        seen = focus
        noticed = start if resumed_at is None else max(start, resumed_at + POLL)
        resumed_at = None
        if change is not None:
            if pending is None:
                pending, pending_since = change, noticed
            else:
                pending = next(kind for kind in PRECEDENCE if kind in (pending, change))
            settled_at = noticed + SETTLE
        while True:
            if pending is None:
                due, trigger = heartbeat_due, "heartbeat"
            else:
                due, trigger = min(settled_at, pending_since + HEARTBEAT), pending
            if last is not None:
                due = max(due, last + RECORD_SPACING)
            due = max(due, start)
            if due >= end or mode is Mode.BLIND:
                break
            kind = EXCLUDED_KIND if excluded else CAPTURE_KIND
            captures.append(Capture(due, trigger, stretch, kind))
            pending, last, heartbeat_due = None, due, due + HEARTBEAT
    records = [*captures, *_sleep_records(timeline), *_pause_records(timeline)]
    return sorted(records, key=lambda capture: capture.at)


def _sleep_records(timeline: Timeline) -> Iterator[Capture]:
    """A slept record unless paused or down, and its woke record unless the agent went down."""
    paused = timeline.faults_of(FaultKind.PAUSED)
    down = timeline.faults_of(FaultKind.AGENT_DOWN)
    for start, end in merge((s.start, s.end) for s in timeline.stretches if not s.active):
        if any(f.start <= start < f.end for f in (*paused, *down)):
            continue
        yield Capture(start, None, None, SLEPT_KIND)
        if end < timeline.end and not any(f.start <= end and start < f.end for f in down):
            yield Capture(end, None, None, WOKE_KIND)


def _pause_records(timeline: Timeline) -> Iterator[Capture]:
    for fault in timeline.faults_of(FaultKind.PAUSED):
        for moment, kind in ((fault.start, PAUSED_KIND), (fault.end, RESUMED_KIND)):
            if moment == timeline.end:
                continue
            if not _agent_awake_at(timeline, moment):
                raise ValueError(f"a pause edge at {moment} falls while the agent cannot see it")
            yield Capture(moment, None, None, kind)


def _agent_awake_at(timeline: Timeline, moment: datetime) -> bool:
    stretch = stretch_at(timeline.stretches, moment)
    down = timeline.faults_of(FaultKind.AGENT_DOWN)
    return stretch.active and not any(f.start <= moment < f.end for f in down)


def _change(seen: Focus | None, focus: Focus) -> str | None:
    if seen is None or seen == focus:
        return None
    if seen[0] != focus[0]:
        return "app"
    return "window" if seen[1] != focus[1] else "title"


def _listening(
    timeline: Timeline,
) -> Iterator[tuple[datetime, datetime, Stretch | None, Mode]]:
    away_since: datetime | None = None
    for stretch, faults in fault_pieces(timeline.stretches, timeline.faults_of(*AGENT_FAULTS)):
        mode = _mode({fault.kind for fault in faults})
        if not stretch.active:
            away_since = None
            yield stretch.start, stretch.end, None, Mode.DOWN if mode is Mode.DOWN else Mode.SILENT
            continue
        if mode is Mode.DOWN:
            away_since = (away_since or stretch.start) if stretch.afk else None
            yield stretch.start, stretch.end, None, mode
            continue
        if not stretch.afk:
            away_since = None
            yield stretch.start, stretch.end, stretch, mode
            continue
        away_since = away_since or stretch.start
        idle = away_since + IDLE_THRESHOLD + PRECISION
        if stretch.start < idle:
            yield stretch.start, min(stretch.end, idle), stretch, mode
        if idle < stretch.end:
            yield max(stretch.start, idle), stretch.end, None, mode


def _mode(kinds: set[FaultKind]) -> Mode:
    if FaultKind.AGENT_DOWN in kinds:
        return Mode.DOWN
    if FaultKind.PAUSED in kinds:
        return Mode.PAUSED
    if FaultKind.EXCLUDED in kinds:
        return Mode.EXCLUDED
    if FaultKind.PERMISSION_LOST in kinds:
        return Mode.BLIND
    return Mode.LISTENING
