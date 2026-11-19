from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from computer_history.sources import Pull, SourceUnavailable
from computer_history.store import Observation, Signal

T0 = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


@dataclass(frozen=True)
class Capture:
    id: str
    start: datetime
    end: datetime


class FakeSource:
    def __init__(self, *streams: str) -> None:
        self.captures: dict[str, list[Capture]] = {stream: [] for stream in streams}
        self.projectors = {stream: self.project for stream in streams}
        self.projected: list[str] = []
        self.strays: dict[str, str] = {}
        self.unsettled: set[str] = set()
        self.down: set[str] = set()
        self.listing_down = False
        self.range_reports_progress = True
        self.before_pull: Callable[[str], None] | None = None
        self.pulled: list[str] = []
        self.positions: list[str] = []

    def add(self, stream: str, capture_id: str, start: float, minutes: float = 1) -> Capture:
        capture = Capture(capture_id, at(start), at(start + minutes))
        self.captures[stream].append(capture)
        return capture

    def streams(self) -> list[str]:
        if self.listing_down:
            raise SourceUnavailable("fake source is not running")
        return list(self.captures)

    def pull_after(self, stream: str, position: str | None, *, now: datetime) -> Pull:
        self._enter(stream)
        offset = 0 if position is None else int(position.rsplit(":", 1)[1])
        taken = []
        for capture in self.captures[stream][offset:]:
            if capture.id in self.unsettled:
                break
            taken.append(capture)
        held = len(self.captures[stream]) - offset - len(taken)
        if not taken:
            return Pull((), held, None, None)
        new_position = f"{stream}.jsonl:{offset + len(taken)}"
        self.positions.append(new_position)
        return Pull(self._observations(stream, taken), held, new_position, taken[-1].end)

    def parts(self, stream: str) -> tuple[str, ...]:
        return (f"{stream}-spool",)

    def history_start(self, stream: str) -> datetime | None:
        return min((capture.start for capture in self.captures[stream]), default=None)

    def history_before(
        self, stream: str, start: datetime
    ) -> tuple[tuple[str, datetime | None], ...]:
        before = [capture.start for capture in self.captures[stream] if capture.start < start]
        return ((f"{stream}-spool", max(before)),) if before else ()

    def pull_range(self, stream: str, start: datetime, end: datetime, *, now: datetime) -> Pull:
        self._enter(stream)
        inside = [c for c in self.captures[stream] if start <= c.start < end]
        held = [c for c in inside if c.id in self.unsettled]
        settled = [c for c in inside if c.id not in self.unsettled]
        observations = self._observations(stream, settled)
        if not self.range_reports_progress:
            return Pull(observations, len(held), None, None)
        until = min(c.start for c in held) if held else min(end, now)
        new_position = f"range:{until.isoformat()}"
        self.positions.append(new_position)
        return Pull(observations, len(held), new_position, until)

    def project(self, payload: str) -> Signal:
        self.projected.append(payload)
        return Signal(title=json.loads(payload)["id"])

    def _enter(self, stream: str) -> None:
        self.pulled.append(stream)
        if self.before_pull is not None:
            self.before_pull(stream)
        if stream in self.down:
            raise SourceUnavailable(f"fake {stream} spool is unreadable")

    def _observations(self, stream: str, captures: list[Capture]) -> tuple[Observation, ...]:
        source = self.strays.get(stream, stream)
        return tuple(
            Observation(source, c.id, c.start, c.end, json.dumps({"id": c.id})) for c in captures
        )
