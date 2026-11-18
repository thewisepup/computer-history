"""One-time, chunked ingest of existing ActivityWatch history (``backfill``).

DESIGN.md §4.1: zero-history installs are the baseline, and backfill is a one-time
convenience for an install that already has AW history. It writes through the
same path as incremental ingest (:func:`ingest_source` with an explicit range), so
the settled-events rule, start-based ownership and dedup all apply unchanged.
Re-running it re-reads AW and inserts nothing.

Range
-----
* **Start (the floor).** AW cannot cheaply say where a bucket's history begins:
  ``limit`` keeps the *newest* events. But a bucket exists before its first event
  is written, so its ``created`` time is a floor that is never too late in normal
  operation. The floor is the earliest ``created`` among the source's buckets,
  rounded down to local midnight (readable chunk edges; a too-early floor only
  costs empty chunks). ``--start`` replaces it.
* **The floor is then checked**, because events imported into AW can predate their
  bucket: one ``limit=1`` probe per bucket asks for the newest event at or before
  the start. If one starts before it, the plan records it as ``earlier`` and the
  CLI warns, naming ``--start``. It does not walk further back on its own.
* **End.** The source's cursor if it has one (incremental polling owns everything
  from there on), else ``now``. ``--end`` can only shorten that.
* **Chunks.** Fixed :data:`BACKFILL_CHUNK` windows, oldest first; the last one is
  shorter. Each is one bounded ``ingest_source(start, end)`` call and one commit.

Completeness
------------
Each chunk's :class:`IngestOutcome` has a ``frontier``: every event starting in
``[chunk.start, frontier)`` is stored. Historical chunks always finish
(``frontier == end``): only a bucket's newest event can be held back. The last
chunk, ending at ``now``, usually holds back the current window/tab/AFK event, so
its ``frontier`` is that event's start. Nothing retries: the run reports it and
``ingest`` picks it up once it settles.

Cursor
------
An explicit range never touches the cursor, so a source that had none would
otherwise make its first ``ingest`` re-read all history from the beginning. When
the source had no cursor at plan time, :func:`run_backfill` therefore sets it at
the end, to ``complete_until``: the frontier of the first incomplete chunk, else
the end of the range. That is only done when the range covered all of the
history (``plan.covers_history``: the probe found nothing before the start), so
the cursor invariant holds: every event starting before it is stored. The write
is :func:`init_cursor`, so a cursor set meanwhile by a concurrent ``ingest
--watch`` wins. An existing cursor is never moved.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple

from computer_history.sources.activitywatch import (
    AWApi,
    AWSource,
    IngestOutcome,
    ingest_source,
)
from computer_history.store import init_cursor, to_utc

__all__ = [
    "BACKFILL_CHUNK",
    "BackfillPlan",
    "BackfillResult",
    "Chunk",
    "plan_backfill",
    "run_backfill",
]

log = logging.getLogger(__name__)

# Per chunk and bucket, ingest_source makes two AW queries (the bucket's newest
# event, then the chunk's range) plus one refetch for each event reaching the
# chunk's end. A week of window events is a few thousand rows, far below what AW
# serves comfortably (and below the POC's 31-day cap).
BACKFILL_CHUNK = timedelta(days=7)
_PROBE_GUARD = timedelta(microseconds=1)


class Chunk(NamedTuple):
    start: datetime
    end: datetime


@dataclass(frozen=True)
class BackfillPlan:
    """What :func:`run_backfill` will pull for one source. Built without writing.

    ``start`` is ``None`` when it could not be determined (no bucket has a usable
    ``created`` time and no explicit start was given); there are no chunks then.
    ``earlier`` lists ``(bucket_id, start)`` of the newest event found before
    ``start`` in each bucket that has one: history the plan does not cover. Its
    ``start`` is ``None`` when that event's timestamp is unreadable; it still
    counts as earlier history (fail safe: the cursor is then not set).
    """

    source: AWSource
    start: datetime | None
    end: datetime
    cursor: datetime | None
    chunks: tuple[Chunk, ...]
    earlier: tuple[tuple[str, datetime | None], ...] = ()

    @property
    def covers_history(self) -> bool:
        """The range starts at or before every event of the source (probe-checked)."""
        return self.start is not None and not self.earlier


@dataclass
class BackfillResult:
    """Running totals of one source's backfill.

    ``incomplete`` holds ``(chunk, frontier)`` for every chunk that ended early.
    ``complete_until``: every event starting in ``[plan.start, complete_until)`` is
    stored. ``cursor_set`` says whether this run wrote the cursor there.
    """

    source: str
    chunks_done: int = 0
    inserted: int = 0
    skipped: int = 0
    held_back: int = 0
    incomplete: list[tuple[Chunk, datetime]] = field(default_factory=list)
    complete_until: datetime | None = None
    cursor_set: bool = False


def plan_backfill(
    client: AWApi,
    source: AWSource,
    *,
    cursor: datetime | str | None,
    now: datetime,
    start: datetime | None = None,
    end: datetime | None = None,
    chunk: timedelta = BACKFILL_CHUNK,
    buckets: Mapping[str, Any] | None = None,
) -> BackfillPlan:
    """The chunked range to backfill for ``source`` (see the module docstring).

    Reads AW (bucket metadata, plus one ``limit=1`` probe per bucket); writes
    nothing. ``cursor`` is the source's cursor at plan time, or ``None``.
    ``buckets`` is AW's bucket listing (``get_buckets()``), if the caller already
    has it; otherwise it is fetched when the start must come from it.
    """
    if chunk <= timedelta(0):
        raise ValueError(f"chunk width must be positive: {chunk}")
    now = to_utc(now)
    cursor_dt = None if cursor is None else to_utc(cursor)
    stop = now if cursor_dt is None else min(cursor_dt, now)
    if end is not None:
        stop = min(stop, to_utc(end))
    if start is not None:
        begin: datetime | None = to_utc(start)
    else:
        begin = _history_floor(client.get_buckets() if buckets is None else buckets, source)
    if begin is None or begin >= stop:
        return BackfillPlan(source, begin, stop, cursor_dt, ())
    earlier = []
    for bucket_id in source.bucket_ids:
        found, began = _event_before(client, bucket_id, begin)
        if found:
            earlier.append((bucket_id, began))
    chunks = []
    edge = begin
    while edge < stop:
        chunks.append(Chunk(edge, min(edge + chunk, stop)))
        edge += chunk
    return BackfillPlan(source, begin, stop, cursor_dt, tuple(chunks), tuple(earlier))


def run_backfill(
    conn: sqlite3.Connection,
    client: AWApi,
    plan: BackfillPlan,
    *,
    on_chunk: Callable[[int, Chunk, IngestOutcome, BackfillResult], None] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> BackfillResult:
    """Ingest every chunk of ``plan`` in order, then set the cursor if it had none.

    Each chunk commits on its own. An error (``AWError``, a locked database, ...)
    propagates after the chunks before it are committed; re-running the backfill
    resumes cheaply, since the done chunks only produce duplicates. ``on_chunk``
    is called after each chunk as ``(index, chunk, outcome, totals_so_far)``.
    ``clock`` (default: UTC now) supplies each chunk's settled-rule ``now``.
    """
    clock = clock or (lambda: datetime.now(UTC))
    result = BackfillResult(plan.source.name)
    for index, piece in enumerate(plan.chunks):
        outcome = ingest_source(
            conn, client, plan.source, start=piece.start, end=piece.end, now=clock()
        )
        result.chunks_done += 1
        result.inserted += outcome.inserted
        result.skipped += outcome.skipped
        result.held_back += outcome.held_back
        if outcome.frontier is not None and outcome.frontier < piece.end:
            result.incomplete.append((piece, outcome.frontier))
        if on_chunk is not None:
            on_chunk(index, piece, outcome, result)
    if plan.chunks:
        result.complete_until = result.incomplete[0][1] if result.incomplete else plan.end
    if plan.cursor is None and plan.covers_history and result.complete_until is not None:
        result.cursor_set = init_cursor(conn, plan.source.name, result.complete_until)
    return result


def _history_floor(buckets: Mapping[str, Any], source: AWSource) -> datetime | None:
    """Local midnight on or before the earliest bucket ``created`` time, if any."""
    created = []
    for bucket_id in source.bucket_ids:
        meta = buckets.get(bucket_id)
        value = meta.get("created") if isinstance(meta, Mapping) else None
        try:
            created.append(to_utc(value))
        except (TypeError, ValueError, AttributeError):
            log.warning("bucket %s has no usable 'created' time (%r)", bucket_id, value)
    if not created:
        return None
    local = min(created).astimezone()
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def _event_before(client: AWApi, bucket_id: str, start: datetime) -> tuple[bool, datetime | None]:
    """``(found, began)`` for the bucket's newest event that begins before ``start``.

    ``(False, None)`` if there is none. ``(True, None)`` if there is one whose
    timestamp cannot be read: it still counts as earlier history, failing safe so
    the cursor is never set past events nobody stored. The query ends just before
    ``start`` (AW's end is inclusive): an event starting exactly at ``start``
    belongs to the first chunk and, as the newest match, would otherwise hide an
    earlier one from a ``limit=1`` query.
    """
    for raw in client.get_events(bucket_id, end=start - _PROBE_GUARD, limit=1):
        try:
            began = to_utc(raw["timestamp"])
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            log.warning(
                "malformed ActivityWatch event in %s before %s: %s; treating it as"
                " history the backfill does not cover",
                bucket_id,
                start.isoformat(),
                exc,
            )
            return True, None
        if began < start:
            return True, began
    return False, None
