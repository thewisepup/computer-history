from __future__ import annotations

import json
import logging
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from computer_history.sources.activitywatch.client import AWApi, AWError
from computer_history.sources.activitywatch.discovery import AWSource, discover_sources
from computer_history.store import Observation, to_utc

log = logging.getLogger(__name__)

STABILITY_MARGIN_SECONDS = 120
CLIP_GUARD = timedelta(seconds=1)
MAX_LOGGED_ID = 64
_END_CLIP_TOLERANCE = timedelta(milliseconds=1)


@dataclass(frozen=True)
class _Event:
    raw: dict[str, Any]
    id: int | str
    start: datetime
    end: datetime


MALFORMED_EVENT = (KeyError, TypeError, ValueError, AttributeError, OverflowError)


def event_times(raw: Any) -> tuple[datetime, datetime]:
    """A raw event's start and end, raising one of MALFORMED_EVENT if they are unusable."""
    start = to_utc(raw["timestamp"])
    duration = float(raw.get("duration") or 0)
    duration = duration if math.isfinite(duration) and duration > 0 else 0.0
    return start, start + timedelta(seconds=duration)


def _parse_event(raw: Any, bucket_id: str) -> _Event | None:
    try:
        event_id = raw["id"]
        if isinstance(event_id, bool) or not isinstance(event_id, int | str) or event_id == "":
            raise ValueError(f"bad id {event_id!r}")
        start, end = event_times(raw)
    except MALFORMED_EVENT as exc:
        raw_id = cast("dict[str, Any]", raw).get("id") if isinstance(raw, dict) else None
        log.warning(
            "malformed event skipped",
            extra={"bucket": bucket_id, "event_id": _loggable(raw_id), "error": type(exc).__name__},
        )
        log.debug(
            "malformed event detail",
            extra={"bucket": bucket_id, "raw_id": repr(raw_id), "error": repr(exc)},
        )
        return None
    return _Event(raw, event_id, start, end)


@dataclass(frozen=True)
class BucketPull:
    """The settled events one bucket contributed to a pull.

    Every event starting before the frontier is included, and held_back counts
    the ones not settled yet.
    """

    bucket_id: str
    observations: tuple[Observation, ...]
    frontier: datetime
    held_back: int


def pull_bucket(
    client: AWApi,
    source: str,
    bucket_id: str,
    *,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    now: datetime | None = None,
) -> BucketPull:
    """The settled events of one bucket that start in the range; writes nothing.

    No start means the beginning of the bucket and no end means up to now, and a pull up to now
    also keeps, whole, any event reaching into the range from before its start.
    """
    now = resolve_now(now)
    start_dt = None if start is None else to_utc(start)
    end_dt = None if end is None else to_utc(end)
    if start_dt is not None and end_dt is not None and end_dt <= start_dt:
        raise ValueError(f"empty pull range: [{start_dt.isoformat()}, {end_dt.isoformat()})")
    settled_before = now - timedelta(seconds=STABILITY_MARGIN_SECONDS)

    newest_raw = client.get_events(bucket_id, limit=1)
    newest = _parse_event(newest_raw[0], bucket_id) if newest_raw else None
    raw_events = client.get_events(
        bucket_id,
        start=None if start_dt is None else start_dt - CLIP_GUARD,
        end=end_dt,
        limit=-1,
    )
    events = [e for e in (_parse_event(raw, bucket_id) for raw in raw_events) if e is not None]
    if start_dt is not None:
        before = [e for e in events if e.start < start_dt]
        events = [e for e in events if e.start >= start_dt]
        if end_dt is None:
            wholes = (_refetch(client, bucket_id, event) for event in before)
            events += [whole for whole in wholes if whole is not None]
    latest_start = max((e.start for e in events), default=None)
    if newest is not None and latest_start is not None:
        latest_start = max(latest_start, newest.start)

    observations: list[Observation] = []
    held: list[_Event] = []
    for event in events:
        assert latest_start is not None
        if end_dt is not None:
            if event.start >= end_dt:
                continue
            if event.end >= end_dt - _END_CLIP_TOLERANCE:
                event = _refetch(client, bucket_id, event)
                if event is None:
                    continue
        if event.start >= latest_start and event.end >= settled_before:
            held.append(event)
            log.debug(
                "event held back: still growing",
                extra={
                    "bucket": bucket_id,
                    "event_id": event.id,
                    "ends": event.end.isoformat(),
                    "title": _shown(event.raw),
                },
            )
        else:
            observations.append(_observation(source, bucket_id, event))

    if held:
        frontier = min(event.start for event in held)
    else:
        frontier = now if end_dt is None else min(end_dt, now)
    return BucketPull(bucket_id, tuple(observations), frontier, len(held))


@dataclass(frozen=True)
class SourcePull:
    """The settled events pulled from every bucket of a source.

    Every event starting before the frontier is included, and held_back counts the rest.
    """

    observations: tuple[Observation, ...]
    held_back: int
    frontier: datetime | None


def pull_source(
    client: AWApi,
    source: AWSource,
    *,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    now: datetime | None = None,
) -> SourcePull:
    """Pull the settled events of every bucket of one source for the range; writes nothing.

    Its frontier is the earliest of the buckets' frontiers.
    """
    now = resolve_now(now)
    pulls = [
        pull_bucket(client, source.name, bucket_id, start=start, end=end, now=now)
        for bucket_id in source.bucket_ids
    ]
    return SourcePull(
        observations=tuple(obs for pull in pulls for obs in pull.observations),
        held_back=sum(pull.held_back for pull in pulls),
        frontier=min((pull.frontier for pull in pulls), default=None),
    )


def newest_events(
    client: AWApi, source_name: str, buckets: Mapping[str, Any]
) -> list[tuple[str, Any]]:
    """The newest raw event of every listed bucket feeding the source, with its bucket id.

    It includes an event still growing.
    """
    return [
        (bucket_id, raw)
        for source in discover_sources(client, buckets=buckets)
        if source.name == source_name
        for bucket_id in source.bucket_ids
        for raw in client.get_events(bucket_id, limit=1)
    ]


def _refetch(client: AWApi, bucket_id: str, clipped: _Event) -> _Event | None:
    raw = client.get_event(bucket_id, clipped.id)
    if raw is None:
        log.warning(
            "event vanished during the pull", extra={"bucket": bucket_id, "event_id": clipped.id}
        )
        return None
    event = _parse_event(raw, bucket_id)
    if event is not None and event.id != clipped.id:
        raise AWError(f"ActivityWatch returned event {event.id} for {bucket_id}/{clipped.id}")
    return event


def _loggable(event_id: object) -> int | str | None:
    if isinstance(event_id, bool):
        return None
    if isinstance(event_id, int) or (isinstance(event_id, str) and len(event_id) <= MAX_LOGGED_ID):
        return event_id
    return None


def _shown(raw: dict[str, Any]) -> str | None:
    data: Any = raw.get("data")
    if not isinstance(data, dict):
        return None
    fields = cast("dict[str, Any]", data)
    shown = fields.get("title") or fields.get("url") or fields.get("status")
    return None if shown is None else str(shown)


def _observation(source: str, bucket_id: str, event: _Event) -> Observation:
    return Observation(
        source=source,
        source_id=f"{bucket_id}/{event.id}",
        started_at=event.start,
        ended_at=event.end,
        payload=json.dumps(event.raw),
    )


def resolve_now(now: datetime | None) -> datetime:
    return datetime.now(UTC) if now is None else to_utc(now)
