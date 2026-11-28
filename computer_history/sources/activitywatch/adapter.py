from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from computer_history.sources.activitywatch.client import AWApi, AWError
from computer_history.sources.activitywatch.discovery import AWSource, discover_sources
from computer_history.sources.activitywatch.history import history_before, history_floor
from computer_history.sources.activitywatch.normalize import PROJECTORS
from computer_history.sources.activitywatch.pull import SourcePull, pull_source
from computer_history.sources.contract import Pull, StreamProjector
from computer_history.sources.progress_moves import ProgressRule, next_position
from computer_history.store import to_utc, utc_iso

RESUME_OVERLAP_SECONDS = 600


class ActivityWatch:
    projectors: Mapping[str, StreamProjector] = PROJECTORS

    def __init__(self, client: AWApi) -> None:
        self.client = client
        self._buckets: Mapping[str, Any] = {}
        self._sources: dict[str, AWSource] | None = None

    def streams(self) -> list[str]:
        return list(self._discover())

    def pull_after(self, stream: str, position: str | None, *, now: datetime) -> Pull:
        start = None if position is None else _resume_start(position)
        pulled = _as_pull(pull_source(self.client, self._source(stream), start=start, now=now))
        rule = ProgressRule.SETTLED_FRONTIER
        return replace(pulled, position=next_position(rule, position, pulled.position, now=now))

    def pull_range(self, stream: str, start: datetime, end: datetime, *, now: datetime) -> Pull:
        pulled = pull_source(self.client, self._source(stream), start=start, end=end, now=now)
        return _as_pull(pulled)

    def parts(self, stream: str) -> tuple[str, ...]:
        return self._source(stream).bucket_ids

    def history_start(self, stream: str) -> datetime | None:
        source = self._source(stream)
        return history_floor(self._buckets, source)

    def history_before(
        self, stream: str, start: datetime
    ) -> tuple[tuple[str, datetime | None], ...]:
        return history_before(self.client, self._source(stream), start)

    def _discover(self) -> dict[str, AWSource]:
        self._buckets = self.client.get_buckets()
        found = discover_sources(self._buckets)
        self._sources = {source.name: source for source in found}
        return self._sources

    def _source(self, stream: str) -> AWSource:
        sources = self._discover() if self._sources is None else self._sources
        if stream not in sources:
            raise AWError(f"ActivityWatch has no buckets for {stream!r}")
        return sources[stream]


def _as_pull(pulled: SourcePull) -> Pull:
    position = None if pulled.frontier is None else _position_at(pulled.frontier)
    return Pull(pulled.observations, pulled.held_back, position, pulled.frontier)


def _position_at(settled_until: datetime) -> str:
    """The position of a stream whose events are all stored up to the given time."""
    return utc_iso(settled_until)


def _resume_start(position: str) -> datetime:
    """Where the next poll starts reading: a little before the stored position."""
    return to_utc(position) - timedelta(seconds=RESUME_OVERLAP_SECONDS)
