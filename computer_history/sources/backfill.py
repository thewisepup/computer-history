"""One-time, chunked ingest of existing ActivityWatch history (backfill).

Backfill writes through the same path as incremental ingest, so the settled
rule, start-based ownership and duplicate handling all apply unchanged.
Re-running it re-reads ActivityWatch and inserts nothing.

The range runs from the earliest bucket's creation time up to the source's
cursor, or now if it has none. --start and --end override that. The range is
ingested in fixed chunks, oldest first, one commit each.

The last chunk usually holds back the current window/tab/AFK event, which a
later ingest picks up once it settles. If the source had no cursor and the
range covered all of its history, the cursor is set at the end, so the next
ingest continues from there instead of re-reading history. An existing cursor
is never moved.
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

BACKFILL_CHUNK = timedelta(days=7)
_PROBE_GUARD = timedelta(microseconds=1)


class Chunk(NamedTuple):
    start: datetime
    end: datetime


@dataclass(frozen=True)
class BackfillPlan:
    """What run_backfill will pull for one source, built without writing anything.

    earlier lists history found before the start that the plan does not cover.
    """

    source: AWSource
    start: datetime | None
    end: datetime
    cursor: datetime | None
    chunks: tuple[Chunk, ...]
    earlier: tuple[tuple[str, datetime | None], ...] = ()

    @property
    def covers_history(self) -> bool:
        """The range starts at or before every event of the source."""
        return self.start is not None and not self.earlier


@dataclass
class BackfillResult:
    """Running totals of one source's backfill.

    Every event starting before complete_until is stored.
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
    """The chunked range to backfill for one source.

    Reads ActivityWatch but writes nothing.
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
    """Ingest every chunk of the plan in order, then set the cursor if it had none.

    Each chunk commits on its own, so re-running after an error resumes cheaply.
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
    """Local midnight on or before the earliest bucket creation time, if any."""
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
    """Whether the bucket has an event beginning before the start, and when it began.

    An event whose timestamp cannot be read still counts as earlier history.
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
