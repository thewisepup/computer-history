"""In-memory ActivityWatch API fake shared by the adapter and CLI tests.

It reproduces the real API's range semantics (overlap filter, inclusive end,
newest-first, ``limit``, and clipping returned events to the query range, as
verified on AW v0.14.2) and satisfies the adapter's ``AWApi`` Protocol.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

from computer_history.store import to_utc

T0 = datetime(2026, 11, 17, 10, 0, 0, 250000, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


class FakeAW:
    def __init__(
        self, buckets: dict[str, str], *, t0: datetime = T0, created: datetime | None = None
    ) -> None:
        self.t0 = t0
        self.buckets = {
            bucket_id: {
                "id": bucket_id,
                "created": (t0 if created is None else created).isoformat(),
                "type": bucket_type,
                "client": "aw-client-web" if bucket_type == "web.tab.current" else bucket_id,
                "hostname": "test-host.local",
                "data": {},
            }
            for bucket_id, bucket_type in buckets.items()
        }
        self.events: dict[str, list[dict[str, Any]]] = {b: [] for b in buckets}
        self.refetches: list[tuple[str, Any]] = []
        self._next_id = 1

    def add(
        self, bucket_id: str, start_minutes: float, duration_seconds: float, data: dict[str, Any]
    ) -> dict:
        raw = {
            "id": self._next_id,
            "timestamp": (self.t0 + timedelta(minutes=start_minutes)).isoformat(),
            "duration": duration_seconds,
            "data": data,
        }
        self._next_id += 1
        self.events[bucket_id].append(raw)
        return raw

    def get_buckets(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self.buckets)

    def get_events(
        self,
        bucket_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = -1,
    ) -> list[dict[str, Any]]:
        found = []
        for raw in self.events[bucket_id]:
            event = copy.deepcopy(raw)
            try:
                ts = to_utc(raw["timestamp"])
                te = ts + timedelta(seconds=raw["duration"])
            except (KeyError, ValueError):
                found.append(event)
                continue
            if (start is not None and te < start) or (end is not None and ts > end):
                continue
            if start is not None and ts < start:
                event["timestamp"], ts = start.isoformat(), start
                event["duration"] = (te - ts).total_seconds()
            if end is not None and te > end:
                event["duration"] = (end - ts).total_seconds()
            found.append(event)
        found.sort(key=_sort_key, reverse=True)
        return found if limit < 0 else found[:limit]

    def get_event(self, bucket_id: str, event_id: Any) -> dict[str, Any] | None:
        self.refetches.append((bucket_id, event_id))
        for raw in self.events[bucket_id]:
            if raw["id"] == event_id:
                return copy.deepcopy(raw)
        return None


def _sort_key(event: dict[str, Any]) -> datetime:
    try:
        return to_utc(event["timestamp"])
    except (KeyError, ValueError):
        return datetime.min.replace(tzinfo=UTC)
