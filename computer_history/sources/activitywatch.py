"""Pull settled ActivityWatch events into the store.

This is the only module that knows ActivityWatch's payload formats. It reads
the ActivityWatch HTTP API (read-only), turns each settled event into an
observation with its signal, and writes each source's batch and its cursor
advance together.

Buckets are discovered by their type, never by name::

    currentwindow   -> aw-window
    afkstatus       -> aw-afk
    web.tab.current -> aw-web

Several buckets may feed one source, and event ids are only unique per bucket,
so source_id is "bucket_id/event_id". The stored payload is the event as
ActivityWatch sent it, re-serialized once from JSON.

How pulling stays safe:

* An event belongs to the pull whose range contains its start time, so a
  stored payload is never a clipped or truncated copy.
* An event that may still be growing (the bucket's latest, ending within the
  stability margin) is held back for a later poll. Held back means delayed,
  never lost.
* The cursor is the frontier: every event starting before it is stored. While
  one window, tab or AFK state lasts, the cursor waits at that event's start,
  so cursor lag grows with the current event. That is expected, not a stall.
* Explicit ranges (backfill) never touch the cursor. The outcome's frontier
  says how much of the range is done; re-pull the rest once it has settled.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, urlopen

from computer_history.store import (
    Cursor,
    Observation,
    Signal,
    get_cursor,
    insert_observations,
    to_utc,
)

__all__ = [
    "AFK_SOURCE",
    "CURSOR_OVERLAP_SECONDS",
    "DEFAULT_AW_URL",
    "STABILITY_MARGIN_SECONDS",
    "WEB_SOURCE",
    "WINDOW_SOURCE",
    "AWApi",
    "AWClient",
    "AWError",
    "AWSource",
    "BucketPull",
    "IngestOutcome",
    "clean_text",
    "clean_url",
    "discover_sources",
    "extract_domain",
    "ingest_all",
    "ingest_source",
    "project_signal",
    "pull_bucket",
]

log = logging.getLogger(__name__)

DEFAULT_AW_URL = "http://127.0.0.1:5600/api/0"
REQUEST_TIMEOUT_SECONDS = 30

# An event that may still be growing is ingested only once its end is older
# than this (twice the 60s poll interval).
STABILITY_MARGIN_SECONDS = 120
# Incremental pulls re-read this much before the cursor; dedup drops the repeats.
CURSOR_OVERLAP_SECONDS = 600
# AW is queried this far before a pull's start, so owned events are never clipped.
CLIP_GUARD = timedelta(seconds=1)
# An owned event ending within this of an explicit query end may be end-clipped.
_END_CLIP_TOLERANCE = timedelta(milliseconds=1)

MAX_TEXT_LENGTH = 2000
MAX_URL_LENGTH = 4096

WINDOW_SOURCE = "aw-window"
AFK_SOURCE = "aw-afk"
WEB_SOURCE = "aw-web"
BUCKET_TYPE_SOURCES = {
    "currentwindow": WINDOW_SOURCE,
    "afkstatus": AFK_SOURCE,
    "web.tab.current": WEB_SOURCE,
}


# --- HTTP client -------------------------------------------------------------


class AWError(RuntimeError):
    """ActivityWatch was unreachable or answered with something unusable."""


class _NotFound(AWError):
    pass


class AWApi(Protocol):
    """The read-only subset of the AW API the adapter uses (fakes implement this)."""

    def get_buckets(self) -> dict[str, dict[str, Any]]: ...

    def get_events(
        self,
        bucket_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = -1,
    ) -> list[dict[str, Any]]: ...

    def get_event(self, bucket_id: str, event_id: Any) -> dict[str, Any] | None: ...


class AWClient:
    """Minimal stdlib (urllib) client for the ActivityWatch REST API. GET only."""

    def __init__(
        self, base_url: str = DEFAULT_AW_URL, timeout: float = REQUEST_TIMEOUT_SECONDS
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_buckets(self) -> dict[str, dict[str, Any]]:
        buckets = self._get("/buckets/")
        if not isinstance(buckets, dict):
            raise AWError("ActivityWatch /buckets/ did not return an object")
        return buckets

    def get_events(
        self,
        bucket_id: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = -1,
    ) -> list[dict[str, Any]]:
        """Events overlapping the range, newest first, clipped to the range.

        The limit keeps the newest events, so a limited page drops the oldest.
        Pass limit=-1 (all) whenever completeness matters.
        """
        params: dict[str, Any] = {"limit": limit}
        if start is not None:
            params["start"] = to_utc(start).isoformat()
        if end is not None:
            params["end"] = to_utc(end).isoformat()
        events = self._get(f"{self._bucket_path(bucket_id)}/events?{urlencode(params)}")
        if not isinstance(events, list):
            raise AWError(f"ActivityWatch events for {bucket_id!r} were not a list")
        return events

    def get_event(self, bucket_id: str, event_id: Any) -> dict[str, Any] | None:
        """One event, unclipped, or None if it no longer exists."""
        try:
            event = self._get(f"{self._bucket_path(bucket_id)}/events/{quote(str(event_id))}")
        except _NotFound:
            return None
        if not isinstance(event, dict):
            raise AWError(f"ActivityWatch event {bucket_id}/{event_id} was not an object")
        return event

    @staticmethod
    def _bucket_path(bucket_id: str) -> str:
        return "/buckets/" + quote(bucket_id, safe="")

    def _get(self, path: str) -> Any:
        url = self.base_url + path
        request = Request(url, headers={"Accept": "application/json"}, method="GET")
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            if exc.code == 404:
                raise _NotFound(f"ActivityWatch 404 for {url}") from exc
            raise AWError(f"ActivityWatch HTTP {exc.code} for {url}") from exc
        except (URLError, OSError) as exc:  # includes timeouts and refused connections
            raise AWError(f"ActivityWatch unreachable at {self.base_url}: {exc}") from exc
        except ValueError as exc:
            raise AWError(f"ActivityWatch returned invalid JSON for {url}") from exc


# --- Discovery ---------------------------------------------------------------


@dataclass(frozen=True)
class AWSource:
    """One store source and the AW buckets that feed it (sorted)."""

    name: str
    bucket_ids: tuple[str, ...]


def discover_sources(client: AWApi, *, buckets: Mapping[str, Any] | None = None) -> list[AWSource]:
    """Map ActivityWatch buckets to store sources by bucket type, sorted by name.

    Buckets of other types are ignored; a source with no bucket is absent.
    Pass a bucket listing you already have, otherwise one is fetched.
    """
    grouped: dict[str, list[str]] = {}
    listing = client.get_buckets() if buckets is None else buckets
    for bucket_id, meta in listing.items():
        bucket_type = meta.get("type") if isinstance(meta, Mapping) else None
        source = BUCKET_TYPE_SOURCES.get(bucket_type) if isinstance(bucket_type, str) else None
        if source is not None:
            grouped.setdefault(source, []).append(bucket_id)
    return [AWSource(name, tuple(sorted(ids))) for name, ids in sorted(grouped.items())]


# --- Normalization (signals) -------------------------------------------------


def project_signal(source: str, payload: Mapping[str, Any] | str) -> Signal | None:
    """The signal for one ActivityWatch event payload, or None for AFK.

    Accepts the event as a dict or as the stored JSON text. rebuild-signals
    re-runs this over stored payloads, so the output must depend on the
    payload alone.
    """
    if source == AFK_SOURCE:
        return None
    if source not in (WINDOW_SOURCE, WEB_SOURCE):
        raise ValueError(f"not an ActivityWatch content source: {source!r}")
    if isinstance(payload, str):
        payload = json.loads(payload)
    raw_data = payload.get("data") if isinstance(payload, Mapping) else None
    data = dict(raw_data) if isinstance(raw_data, Mapping) else {}
    if source == WINDOW_SOURCE:
        app = clean_text(_take_str(data, "app"))
        title = clean_text(_take_str(data, "title"))
        return Signal(app=app, title=title, extras=_extras(data))
    url = _take_str(data, "url")
    title = clean_text(_take_str(data, "title"))
    return Signal(
        url=clean_url(url), domain=extract_domain(url), title=title, extras=_extras(data)
    )


def clean_text(value: str | None, limit: int = MAX_TEXT_LENGTH) -> str | None:
    """Whitespace stripped and collapsed, length capped; empty becomes None."""
    if value is None:
        return None
    return " ".join(_scrub(value).split())[:limit] or None


def clean_url(value: str | None) -> str | None:
    """Control characters removed, trimmed, length capped; empty becomes None."""
    if value is None:
        return None
    return _sanitize_url(value)[:MAX_URL_LENGTH] or None


def extract_domain(url: str | None) -> str | None:
    """Lowercased host of an http(s) URL, without port or a leading www.

    Missing, unparseable and non-web URLs (chrome://, file://, ...) become None.
    """
    if not url:
        return None
    try:
        parts = urlsplit(_sanitize_url(url))
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    host = host.rstrip(".")
    if host.startswith("www."):
        host = host[len("www.") :]
    return host or None


def _take_str(data: dict[str, Any], key: str) -> str | None:
    """Pop the key if it holds a string; anything else stays behind for extras."""
    value = data.get(key)
    if isinstance(value, str):
        del data[key]
        return value
    return None


def _extras(leftover: dict[str, Any]) -> str | None:
    # Sorted keys: a rebuild must reproduce the same text byte for byte.
    return json.dumps(leftover, sort_keys=True) if leftover else None


# Control characters: a real URL never contains them unencoded.
_URL_CONTROL_CHARS = dict.fromkeys([*range(0x20), 0x7F])


def _sanitize_url(value: str) -> str:
    """Remove control characters anywhere; trim spaces at the ends."""
    return _scrub(value).translate(_URL_CONTROL_CHARS).strip(" ")


def _scrub(value: str) -> str:
    # Replace broken characters (lone surrogates) that SQLite cannot store.
    return value.encode("utf-8", "replace").decode("utf-8")


# --- Pulling -----------------------------------------------------------------


@dataclass(frozen=True)
class _Event:
    raw: dict[str, Any]
    id: int | str
    start: datetime
    end: datetime


def _parse_event(raw: Any, bucket_id: str) -> _Event | None:
    """Timing for one raw event; None (logged) if it is malformed."""
    try:
        event_id = raw["id"]
        if isinstance(event_id, bool) or not isinstance(event_id, int | str) or event_id == "":
            raise ValueError(f"bad id {event_id!r}")
        start = to_utc(raw["timestamp"])
        duration = float(raw.get("duration") or 0)
        # A negative or non-finite duration becomes zero; the payload keeps the original.
        duration = duration if math.isfinite(duration) and duration > 0 else 0.0
        end = start + timedelta(seconds=duration)
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        log.warning("skipping malformed ActivityWatch event in %s: %s", bucket_id, exc)
        return None
    return _Event(raw, event_id, start, end)


@dataclass(frozen=True)
class BucketPull:
    """The settled events one bucket owns in a pull, and how far they reach.

    Every event starting in the pull's range before the frontier is included;
    held_back counts owned events not yet settled.
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
    """Settled events of one bucket that start in the range. Writes nothing.

    No start means the beginning of the bucket; no end means up to now.
    """
    now = _now(now)
    start_dt = None if start is None else to_utc(start)
    end_dt = None if end is None else to_utc(end)
    if start_dt is not None and end_dt is not None and end_dt <= start_dt:
        raise ValueError(f"empty pull range: [{start_dt.isoformat()}, {end_dt.isoformat()})")
    settled_before = now - timedelta(seconds=STABILITY_MARGIN_SECONDS)

    # Read the bucket's newest event before the range: anything created in
    # between only makes the settled rule more cautious.
    newest_raw = client.get_events(bucket_id, limit=1)
    newest = _parse_event(newest_raw[0], bucket_id) if newest_raw else None
    raw_events = client.get_events(
        bucket_id,
        start=None if start_dt is None else start_dt - CLIP_GUARD,
        end=end_dt,
        limit=-1,
    )
    events = [e for e in (_parse_event(raw, bucket_id) for raw in raw_events) if e is not None]
    latest_start = max((e.start for e in events), default=None)
    if newest is not None and latest_start is not None:
        latest_start = max(latest_start, newest.start)

    observations: list[Observation] = []
    held: list[_Event] = []
    for event in events:
        if start_dt is not None and event.start < start_dt:
            continue  # starts before the range (possibly start-clipped): not ours
        if end_dt is not None:
            if event.start >= end_dt:
                continue  # AW's end is inclusive; ours is exclusive
            if event.end >= end_dt - _END_CLIP_TOLERANCE:
                event = _refetch(client, bucket_id, event)  # possibly end-clipped
                if event is None:
                    continue
        if event.start >= latest_start and event.end >= settled_before:
            held.append(event)
        else:
            observations.append(_observation(source, bucket_id, event))

    if held:
        frontier = min(event.start for event in held)
    else:
        frontier = now if end_dt is None else min(end_dt, now)
    return BucketPull(bucket_id, tuple(observations), frontier, len(held))


def _refetch(client: AWApi, bucket_id: str, clipped: _Event) -> _Event | None:
    raw = client.get_event(bucket_id, clipped.id)
    if raw is None:
        log.warning("ActivityWatch event %s/%s vanished during the pull", bucket_id, clipped.id)
        return None
    event = _parse_event(raw, bucket_id)
    if event is not None and event.id != clipped.id:
        raise AWError(f"ActivityWatch returned event {event.id} for {bucket_id}/{clipped.id}")
    return event


def _observation(source: str, bucket_id: str, event: _Event) -> Observation:
    return Observation(
        source=source,
        source_id=f"{bucket_id}/{event.id}",
        started_at=event.start,
        ended_at=event.end,
        # Stored as received, re-serialized once from JSON.
        payload=json.dumps(event.raw),
        signal=project_signal(source, event.raw),
    )


# --- Ingest ------------------------------------------------------------------


def ingest_source(
    conn: sqlite3.Connection,
    client: AWApi,
    source: AWSource,
    *,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    now: datetime | None = None,
) -> IngestOutcome:
    """Pull one source's buckets and write the batch and cursor together.

    With no explicit range this is an incremental poll: it reads from a little
    before the cursor (or from the beginning) and advances the cursor in the
    same transaction. An explicit range (backfill) leaves the cursor alone;
    check the outcome's frontier to know whether the whole range is done. If
    any bucket's pull fails, nothing is written for the source.
    """
    now = _now(now)
    incremental = start is None and end is None
    if incremental:
        cursor = get_cursor(conn, source.name)
        if cursor is not None:
            start = to_utc(cursor) - timedelta(seconds=CURSOR_OVERLAP_SECONDS)
    pulls = [
        pull_bucket(client, source.name, bucket_id, start=start, end=end, now=now)
        for bucket_id in source.bucket_ids
    ]
    frontier = min((pull.frontier for pull in pulls), default=None)
    advance = Cursor(source.name, frontier) if incremental and frontier is not None else None
    observations = [obs for pull in pulls for obs in pull.observations]
    result = insert_observations(conn, observations, advance_cursor=advance)
    return IngestOutcome(
        inserted=result.inserted,
        skipped=result.skipped,
        held_back=sum(pull.held_back for pull in pulls),
        frontier=frontier,
    )


class IngestOutcome(NamedTuple):
    """What one ingest_source call did.

    held_back counts events not yet settled, so not written. frontier is how
    far the pull reached: every event starting before it is now stored. A
    frontier short of the requested end means the range is incomplete; re-pull
    the rest once it has settled. None means the source had no buckets.
    """

    inserted: int
    skipped: int
    held_back: int
    frontier: datetime | None


def ingest_all(
    conn: sqlite3.Connection, client: AWApi, *, now: datetime | None = None
) -> dict[str, IngestOutcome]:
    """One incremental poll of every discovered source, keyed by source name.

    Each source commits on its own. An error stops the poll there, and the sources
    already written stay committed.
    """
    now = _now(now)
    return {
        source.name: ingest_source(conn, client, source, now=now)
        for source in discover_sources(client)
    }


def _now(now: datetime | None) -> datetime:
    return datetime.now(UTC) if now is None else to_utc(now)
