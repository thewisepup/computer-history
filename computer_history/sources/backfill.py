"""One-time, chunked ingest of existing ActivityWatch history (backfill).

Each chunk commits on its own, oldest first, and the last chunk's commit also
sets the source's progress if it had none and the range covered its history.
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
    discover_sources,
    outcome_of,
    progress_at,
    pull_source,
)
from computer_history.store import Progress, get_progress, insert_observations, to_utc

__all__ = [
    "BACKFILL_CHUNK",
    "BackfillPlan",
    "BackfillResult",
    "Chunk",
    "plan_all_backfills",
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
    settled_until: datetime | None
    chunks: tuple[Chunk, ...]
    earlier: tuple[tuple[str, datetime | None], ...] = ()
    has_progress: bool = False

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
    progress_set: bool = False


def plan_backfill(
    client: AWApi,
    source: AWSource,
    *,
    progress: Progress | None,
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
    settled = None if progress is None else progress.settled_until
    stop = now if settled is None else min(settled, now)
    if end is not None:
        stop = min(stop, to_utc(end))
    if start is not None:
        begin: datetime | None = to_utc(start)
    else:
        begin = _history_floor(client.get_buckets() if buckets is None else buckets, source)
    if begin is None or begin >= stop:
        return BackfillPlan(source, begin, stop, settled, (), has_progress=progress is not None)
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
    return BackfillPlan(
        source,
        begin,
        stop,
        settled,
        tuple(chunks),
        tuple(earlier),
        has_progress=progress is not None,
    )


def plan_all_backfills(
    conn: sqlite3.Connection | None,
    client: AWApi,
    *,
    now: datetime,
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[BackfillPlan]:
    """Plan every discovered source from its stored progress, or from none without a database.

    Lists the buckets once and writes nothing.
    """
    buckets = client.get_buckets()
    return [
        plan_backfill(
            client,
            source,
            progress=None if conn is None else get_progress(conn, source.name),
            now=now,
            start=start,
            end=end,
            buckets=buckets,
        )
        for source in discover_sources(client, buckets=buckets)
    ]


def run_backfill(
    conn: sqlite3.Connection,
    client: AWApi,
    plan: BackfillPlan,
    *,
    on_chunk: Callable[[int, Chunk, IngestOutcome, BackfillResult], None] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> BackfillResult:
    """Ingest every chunk of the plan in order, each in its own commit.

    The last commit also sets the source's progress if it had none and the plan covers its history.
    """
    clock = clock or (lambda: datetime.now(UTC))
    result = BackfillResult(plan.source.name)
    last = len(plan.chunks) - 1
    for index, piece in enumerate(plan.chunks):
        now = clock()
        pulled = pull_source(client, plan.source, start=piece.start, end=piece.end, now=now)
        incomplete = list(result.incomplete)
        if pulled.frontier is not None and pulled.frontier < piece.end:
            incomplete.append((piece, pulled.frontier))
        complete_until = incomplete[0][1] if incomplete else plan.end
        progress = (
            progress_at(plan.source.name, complete_until, only_if_none=True)
            if index == last and not plan.has_progress and plan.covers_history
            else None
        )
        written = insert_observations(conn, pulled.observations, progress=progress, now=now)
        outcome = outcome_of(pulled, written)
        result.chunks_done += 1
        result.inserted += outcome.inserted
        result.skipped += outcome.skipped
        result.held_back += outcome.held_back
        result.incomplete = incomplete
        if index == last:
            result.complete_until = complete_until
            result.progress_set = written.progress_moved
        if on_chunk is not None:
            on_chunk(index, piece, outcome, result)
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
