"""Rendered ActivityWatch buckets served in process, with the real API's range semantics."""

from __future__ import annotations

import copy
from bisect import bisect_left, bisect_right
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from computer_history.store import to_utc


@dataclass(frozen=True)
class AWEvent:
    """One event as aw-server stores it once heartbeats have merged."""

    id: int
    start: datetime
    end: datetime
    data: Mapping[str, Any]

    def raw(self, start: datetime | None = None, end: datetime | None = None) -> dict[str, Any]:
        """The event as the API returns it, clipped to the given bounds."""
        begin = self.start if start is None else max(self.start, start)
        finish = self.end if end is None else min(self.end, end)
        return {
            "id": self.id,
            "timestamp": begin.isoformat(),
            "duration": (finish - begin).total_seconds(),
            "data": copy.deepcopy(dict(self.data)),
        }


class ServedAW:
    """Serves rendered buckets in process the way the ActivityWatch API does."""

    def __init__(
        self,
        buckets: Mapping[str, Mapping[str, Any]],
        events: Mapping[str, tuple[AWEvent, ...]],
    ) -> None:
        for bucket, found in events.items():
            if any(a.end > b.start for a, b in zip(found, found[1:], strict=False)):
                raise ValueError(f"events in {bucket} overlap or are out of order")
        self.buckets = buckets
        self.events = events
        self.starts = {bucket: [e.start for e in found] for bucket, found in events.items()}
        self.ends = {bucket: [e.end for e in found] for bucket, found in events.items()}
        self.by_id = {
            bucket: {event.id: event for event in found} for bucket, found in events.items()
        }

    def get_buckets(self) -> dict[str, dict[str, Any]]:
        return {bucket: copy.deepcopy(dict(meta)) for bucket, meta in self.buckets.items()}

    def get_events(
        self,
        bucket_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = -1,
    ) -> list[dict[str, Any]]:
        found = self.events[bucket_id]
        start = None if start is None else to_utc(start)
        end = None if end is None else to_utc(end)
        first = 0 if start is None else bisect_left(self.ends[bucket_id], start)
        last = len(found) if end is None else bisect_right(self.starts[bucket_id], end)
        newest_first = found[first:last][::-1]
        if limit >= 0:
            newest_first = newest_first[:limit]
        return [event.raw(start, end) for event in newest_first]

    def get_event(self, bucket_id: str, event_id: Any) -> dict[str, Any] | None:
        event = self.by_id[bucket_id].get(event_id)
        return None if event is None else event.raw()
