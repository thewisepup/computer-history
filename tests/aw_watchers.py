"""ActivityWatch's window and AFK watchers and its heartbeat merge, on a simulated clock.

Each follows the upstream source line for line, so ingest meets buckets that grow as real ones do.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fake_aw import FakeAW

from computer_history.store import to_utc

WINDOW_BUCKET = "aw-watcher-window_test-host.local"
AFK_BUCKET = "aw-watcher-afk_test-host.local"

AFK_TIMEOUT = 180.0
AFK_POLL_TIME = 5
AFK_PULSETIME = AFK_TIMEOUT + AFK_POLL_TIME
WINDOW_PULSETIME = max(1.0 * 1.5, 1.0 + 1.0)
TD1MS = timedelta(milliseconds=1)

T0 = datetime(2026, 11, 17, 9, 0, tzinfo=UTC)


class HeartbeatAW(FakeAW):
    """The fake ActivityWatch API, taking heartbeats the way aw-server-rust merges them.

    It starts with no buckets: each watcher creates its own when it starts.
    """

    def __init__(self) -> None:
        super().__init__({}, t0=T0)

    def heartbeat(
        self,
        bucket_id: str,
        timestamp: datetime,
        data: dict[str, Any],
        *,
        pulsetime: float,
        duration: float = 0.0,
    ) -> None:
        """Merge the heartbeat into the bucket's last event, or store it as a new event."""
        events = self.events[bucket_id]
        last = max(events, key=lambda raw: to_utc(raw["timestamp"])) if events else None
        if last is not None and last["data"] == data:
            last_start = to_utc(last["timestamp"])
            last_end = last_start + timedelta(seconds=last["duration"])
            beat_end = timestamp + timedelta(seconds=duration)
            if last_start <= timestamp <= last_end + timedelta(seconds=pulsetime):
                last["duration"] = (max(last_end, beat_end) - last_start).total_seconds()
                return
        events.append(
            {
                "id": self._next_id,
                "timestamp": timestamp.isoformat(),
                "duration": duration,
                "data": dict(data),
            }
        )
        self._next_id += 1


class WindowWatcher:
    """aw-watcher-window: a heartbeat of the focused app every second."""

    def __init__(self, aw: HeartbeatAW) -> None:
        self.aw = aw

    def tick(self, now: datetime, app: str) -> None:
        self.aw.create_bucket(WINDOW_BUCKET, "currentwindow", now)
        data = {"app": app, "title": app}
        self.aw.heartbeat(WINDOW_BUCKET, now, data, pulsetime=WINDOW_PULSETIME)


class AfkWatcher:
    """aw-watcher-afk's heartbeat loop, without screen locking."""

    def __init__(self, aw: HeartbeatAW) -> None:
        self.aw = aw
        self.afk = False
        self.afk_start: datetime | None = None
        self.not_afk_start: datetime | None = None

    def tick(self, now: datetime, last_input: datetime) -> None:
        self.aw.create_bucket(AFK_BUCKET, "afkstatus", now)
        since = (now - last_input).total_seconds()
        if self.not_afk_start is not None and last_input < self.not_afk_start:
            last_input = self.not_afk_start
        if self.afk and since < AFK_TIMEOUT:
            unlocked = self.afk_start is not None and last_input <= self.afk_start
            afk_end = now if unlocked else last_input
            self.afk_start = None
            self.not_afk_start = afk_end
            self._ping(True, afk_end)
            self.afk = False
            self._ping(False, afk_end + TD1MS)
        elif not self.afk and since >= AFK_TIMEOUT:
            self.afk_start = last_input
            self.not_afk_start = None
            self._ping(False, last_input)
            self.afk = True
            self._ping(True, last_input + TD1MS, (now - last_input).total_seconds())
        elif self.afk:
            start = self.afk_start or last_input
            self._ping(True, start + TD1MS, (now - start).total_seconds())
        else:
            ts = last_input
            if self.not_afk_start is not None and ts < self.not_afk_start + TD1MS:
                ts = self.not_afk_start + TD1MS
            self._ping(False, ts)

    def _ping(self, afk: bool, timestamp: datetime, duration: float = 0.0) -> None:
        data = {"status": "afk" if afk else "not-afk"}
        self.aw.heartbeat(AFK_BUCKET, timestamp, data, pulsetime=AFK_PULSETIME, duration=duration)


@dataclass(frozen=True)
class Stretch:
    """A stretch of the day: the user at the Mac, idle in front of it, or the Mac asleep."""

    kind: str  # 'active' | 'idle' | 'asleep'
    seconds: int
    app: str


@dataclass(frozen=True)
class Day:
    """The stretches in order, and when ingest polls in seconds of awake time."""

    stretches: tuple[Stretch, ...]
    poll_phase: int
    afk_phase: int
    extra_polls: tuple[int, ...] = ()


Poll = Callable[[datetime], object]

POLL_EVERY = 60
DRAIN_AFTER = timedelta(minutes=30)


def live_through(day: Day, aw: HeartbeatAW, poll: Poll) -> None:
    """Run the watchers and polls second by second, then stop the watchers and poll once more."""
    window, afk = WindowWatcher(aw), AfkWatcher(aw)
    now = last_input = T0
    awake = 0
    for stretch in day.stretches:
        for _ in range(stretch.seconds):
            if stretch.kind != "asleep":
                if stretch.kind == "active":
                    last_input = now
                window.tick(now, stretch.app)
                if awake % AFK_POLL_TIME == day.afk_phase:
                    afk.tick(now, last_input)
                if awake % POLL_EVERY == day.poll_phase or awake in day.extra_polls:
                    poll(now)
                awake += 1
            now += timedelta(seconds=1)
    poll(now + DRAIN_AFTER)


def bucket_events(aw: HeartbeatAW, bucket_id: str) -> dict[str, tuple[str, float]]:
    """Each event ActivityWatch holds, by its source id: when it starts and how long it lasts."""
    return {
        f"{bucket_id}/{raw['id']}": (raw["timestamp"], raw["duration"])
        for raw in aw.events.get(bucket_id, [])
    }


def stored_events(conn: sqlite3.Connection, stream: str) -> dict[str, tuple[str, float]]:
    """Each stored observation of the stream, by its source id, as its payload gives it."""
    rows = conn.execute("SELECT source_id, payload FROM observations WHERE source = ?", (stream,))
    stored = {}
    for source_id, payload in rows:
        raw = json.loads(payload)
        stored[source_id] = (raw["timestamp"], raw["duration"])
    return stored
