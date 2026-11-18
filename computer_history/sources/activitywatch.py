"""ActivityWatch adapter (DESIGN.md §4.1): pull settled AW events into the store.

This is the only module that knows ActivityWatch's payload dialects. It reads the
AW HTTP API (read-only, GET only), turns each settled event into an
:class:`Observation` with its :class:`Signal` projection, and writes each source's
batch and its cursor advance in one :func:`insert_observations` call.

Sources and buckets
-------------------
Buckets are discovered by their ``type``, never by name (names embed hostnames,
and the web watcher's client is ``aw-client-web``, not ``aw-watcher-web``)::

    currentwindow   -> aw-window
    afkstatus       -> aw-afk
    web.tab.current -> aw-web

Several buckets may feed one source (this Mac has two Chrome buckets, one of them
dead). AW event ids are not unique across buckets, so
``source_id = f"{bucket_id}/{event_id}"``.

``observations.payload`` is the AW event object as received, **verbatim up to a
JSON round-trip**: ``json.dumps(json.loads(...))`` keeps AW's key order and
every value, but not AW's byte-level formatting (whitespace, number spelling,
and non-ASCII written as ``\\u`` escapes). Events arrive inside one list
response, so their original bytes are not separately available.

Pull semantics (why the cursor is a *start* time)
-------------------------------------------------
AW clips the events it returns to the query's ``[start, end]`` (checked against
v0.14.2): an event that straddles a query edge comes back with a shortened
``timestamp``/``duration``. Dedup keeps the first version of a row forever, so a
clipped first copy would be stored truncated for good. The aw-server range query
also skips events that began more than 24h before ``start``. Both problems go
away if an event is **owned by its start time**:

* A pull over ``[start, end)`` is responsible for exactly the events whose
  ``timestamp`` lies in that range. AW is queried from ``start - CLIP_GUARD``, so
  an owned event can never be start-clipped. An event that comes back starting
  before ``start`` (unowned, or clipped) is ignored: it belongs to an earlier
  pull.
* With an explicit ``end``, an owned event that reaches the query end may have
  been end-clipped, so it is re-fetched whole with ``GET .../events/{id}``.
  Incremental pulls send no ``end``, so nothing is end-clipped there.
* **Settled-events rule.** An owned event is ingested if it is not possibly the
  bucket's latest event, or if its end is older than ``now - STABILITY_MARGIN``.
  An event is possibly the latest when it starts no earlier than the bucket's
  newest event (read first with ``limit=1``) *and* no earlier than every other
  event in the range response. AW only ever extends the last event, so an event
  with a newer one beside it in the same response is final as returned. Ties
  count as latest. The rule errs toward holding an event back for a poll, never
  toward ingesting one that is still growing.
* **Frontier** of a bucket pull: the start of the earliest event held back, or, if
  none, the pull's ``end`` (``now`` for an open-ended pull). Every owned event that
  starts before the frontier is in the batch.
* **Cursor** (``ingest_cursors``, one per source) = the minimum frontier over the
  source's buckets. Invariant: every event that starts before the cursor has
  been ingested. A dead bucket has nothing held back, so its frontier is ``now``
  and it never pins the cursor. The cursor may move backwards, for example when
  an event arrives late and becomes the held latest event. That is correct.
* The next incremental pull starts at ``cursor - CURSOR_OVERLAP_SECONDS``. The
  invariant needs no overlap at all. The overlap is a cheap safety net for
  events that reach AW late with older timestamps (aw-client queues heartbeats
  while the server is down), and dedup drops the re-read rows.

* **Explicit ranges (backfill)** never touch the cursor. Their
  :class:`IngestOutcome` reports ``held_back`` and ``frontier``: every event
  starting in ``[start, frontier)`` is stored. If ``frontier < end``, the rest of
  the range is not done yet, either because events there have not settled
  (``held_back > 0``) or because the range runs past ``now``. Re-pull
  ``[frontier, end)`` later.

While one window, tab or AFK state lasts, the cursor sits at that event's start,
so cursor lag ("now - cursor") grows to the current event's duration. That is
expected, not a stall.
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
    get_mapping_version,
    insert_observations,
    set_mapping_version,
    to_utc,
)

__all__ = [
    "AFK_SOURCE",
    "CURSOR_OVERLAP_SECONDS",
    "DEFAULT_AW_URL",
    "MAPPING_VERSION",
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

# An event still possibly growing (the bucket's latest) is ingested only once its
# end is older than this. 2x the 60s poll interval (map decision, 2026-11-17).
STABILITY_MARGIN_SECONDS = 120
# Incremental pulls re-read this much before the cursor; dedup drops the repeats.
CURSOR_OVERLAP_SECONDS = 600
# AW is queried this far before a pull's start, so owned events are never clipped.
CLIP_GUARD = timedelta(seconds=1)
# An owned event ending within this of an explicit query end may be end-clipped.
_END_CLIP_TOLERANCE = timedelta(milliseconds=1)

# Bump whenever project_signal()'s output changes; rebuild-signals compares it
# with the version recorded in signals_meta.
MAPPING_VERSION = 1
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
        """Events overlapping ``[start, end]``, newest first, **clipped to the range**.

        AW applies ``limit`` newest-first, so a limited page drops the oldest
        events. Pass ``limit=-1`` (all) whenever completeness matters.
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
        """One event, unclipped, or ``None`` if it no longer exists."""
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


def discover_sources(client: AWApi) -> list[AWSource]:
    """Map AW buckets to store sources by bucket type; sorted by source name.

    Buckets of other types are ignored. A source with no bucket is absent.
    """
    grouped: dict[str, list[str]] = {}
    for bucket_id, meta in client.get_buckets().items():
        bucket_type = meta.get("type") if isinstance(meta, Mapping) else None
        source = BUCKET_TYPE_SOURCES.get(bucket_type) if isinstance(bucket_type, str) else None
        if source is not None:
            grouped.setdefault(source, []).append(bucket_id)
    return [AWSource(name, tuple(sorted(ids))) for name, ids in sorted(grouped.items())]


# --- Normalization (signals) -------------------------------------------------


def project_signal(source: str, payload: Mapping[str, Any] | str) -> Signal | None:
    """The :class:`Signal` for one AW event payload, or ``None`` for AFK (§4.3).

    ``payload`` is the AW event (``{"id", "timestamp", "duration", "data"}``), as a
    dict or as the JSON text stored in ``observations.payload``. ``rebuild-signals``
    re-runs this over stored payloads, so the output must depend on the payload
    alone. Bump :data:`MAPPING_VERSION` whenever the output changes.
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
    """Text hygiene (§3.2): whitespace stripped and collapsed, capped; empty -> None."""
    if value is None:
        return None
    return " ".join(_scrub(value).split())[:limit] or None


def clean_url(value: str | None) -> str | None:
    """The stored ``signals.url``: :func:`_sanitize_url`, capped; empty -> ``None``."""
    if value is None:
        return None
    return _sanitize_url(value)[:MAX_URL_LENGTH] or None


def extract_domain(url: str | None) -> str | None:
    """Lowercased host of an http(s) URL, without port or a leading ``www.``.

    Missing, unparseable and non-web URLs (``chrome://``, ``file://``, ...) -> ``None``.
    It parses the same sanitized string that :func:`clean_url` stores.
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
    """Pop ``key`` if it holds a string; anything else stays behind for ``extras``."""
    value = data.get(key)
    if isinstance(value, str):
        del data[key]
        return value
    return None


def _extras(leftover: dict[str, Any]) -> str | None:
    # Sorted keys: a rebuild must reproduce the same text byte for byte.
    return json.dumps(leftover, sort_keys=True) if leftover else None


# C0 controls and DEL. Covers urlsplit's own cleanup (WHATWG: tab/CR/LF removed
# anywhere, C0+space stripped at the ends) and the stray controls it would keep.
_URL_CONTROL_CHARS = dict.fromkeys([*range(0x20), 0x7F])


def _sanitize_url(value: str) -> str:
    """Control characters removed anywhere, spaces trimmed at the ends.

    A real URL never contains a raw control character (they must be
    percent-encoded), so removing them loses nothing a browser would send.
    """
    return _scrub(value).translate(_URL_CONTROL_CHARS).strip(" ")


def _scrub(value: str) -> str:
    # Lone surrogates (broken emoji in window titles) survive json.loads but cannot
    # be encoded for SQLite; replace them rather than fail the whole batch.
    return value.encode("utf-8", "replace").decode("utf-8")


# --- Pulling -----------------------------------------------------------------


@dataclass(frozen=True)
class _Event:
    raw: dict[str, Any]
    id: int | str
    start: datetime
    end: datetime


def _parse_event(raw: Any, bucket_id: str) -> _Event | None:
    """Timing for one raw AW event; ``None`` (logged) if it is malformed."""
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

    ``frontier``: every event in the bucket that starts in the pull's range and
    before ``frontier`` is in ``observations``. ``held_back`` counts owned events
    not yet settled.
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
    """Settled events of one bucket that *start* in ``[start, end)``. Writes nothing.

    ``start=None`` means the beginning of the bucket. ``end=None`` means open-ended
    (up to now). See the module docstring for the clipping and settled rules.
    """
    now = _now(now)
    start_dt = None if start is None else to_utc(start)
    end_dt = None if end is None else to_utc(end)
    if start_dt is not None and end_dt is not None and end_dt <= start_dt:
        raise ValueError(f"empty pull range: [{start_dt.isoformat()}, {end_dt.isoformat()})")
    settled_before = now - timedelta(seconds=STABILITY_MARGIN_SECONDS)

    # The bucket's newest event first, then the range: an event created in between
    # starts at or after `newest`, so it can only make the rule more conservative.
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
        # Verbatim up to a JSON round-trip (module docstring): AW's key order and
        # values are kept. ensure_ascii's \u escapes also keep lone surrogates storable.
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
    """Pull one source's buckets and write the batch in one ``insert_observations``.

    With neither ``start`` nor ``end`` this is an incremental poll: it reads from
    ``cursor - CURSOR_OVERLAP_SECONDS`` (or from the beginning if there is no
    cursor) and advances the cursor to the minimum bucket frontier in the same
    transaction. An explicit range (backfill) ingests the settled events that
    start in ``[start, end)`` and leaves the cursor alone; check the outcome's
    ``frontier`` (see :class:`IngestOutcome`) to know whether the whole range is
    done. If any bucket's pull fails, no observations are written for the source.
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
    # Seed the mapping version BEFORE the first signal can exist, never after. It
    # cannot join insert_observations' transaction (that call opens its own), so
    # order is the guarantee: "no meta row" then always means "no signals". If the
    # batch fails, meta=MAPPING_VERSION with zero signals is vacuously true. The
    # reverse order is unsafe: a crash between the two would leave signals without
    # a meta row, and a later code version would then record itself over them, so
    # rebuild-signals would never notice the mismatch.
    if get_mapping_version(conn) is None:
        set_mapping_version(conn, MAPPING_VERSION)
    observations = [obs for pull in pulls for obs in pull.observations]
    result = insert_observations(conn, observations, advance_cursor=advance)
    return IngestOutcome(
        inserted=result.inserted,
        skipped=result.skipped,
        held_back=sum(pull.held_back for pull in pulls),
        frontier=frontier,
    )


class IngestOutcome(NamedTuple):
    """What one :func:`ingest_source` call did.

    ``inserted``/``skipped`` are the store's counts. ``held_back`` counts owned
    events not yet settled, so not written. ``frontier`` is the minimum bucket
    frontier: every event starting in ``[start, frontier)`` is now stored. For an
    incremental poll it is the cursor just written. For an explicit range,
    ``frontier < end`` means the range is incomplete, so re-pull ``[frontier, end)``
    once it has settled. ``None`` means the source had no buckets.
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
