from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import NamedTuple

from computer_history.logs import Outcome, progress_step
from computer_history.sources.commit import (
    StrayObservation,
    StreamFailure,
    commit_pull,
    failure_of,
)
from computer_history.sources.contract import HistorySource, Pull, SourceUnavailable
from computer_history.sources.projection import projector_for
from computer_history.store import Progress, Projector, UnclaimedSource, get_progress, to_utc

__all__ = [
    "BACKFILL_CHUNK",
    "BackfillPlan",
    "BackfillProgress",
    "BackfillResult",
    "Chunk",
    "ChunkDone",
    "plan_all_backfills",
    "plan_backfill",
    "run_backfill",
]

BACKFILL_CHUNK = timedelta(days=7)

log = logging.getLogger(__name__)

Clock = Callable[[], datetime]


class Chunk(NamedTuple):
    start: datetime
    end: datetime


@dataclass(frozen=True)
class BackfillPlan:
    """What a backfill will pull for one stream, built without writing anything.

    earlier lists parts with history before the start that the plan does not cover.
    """

    stream: str
    parts: tuple[str, ...]
    start: datetime | None
    end: datetime
    settled_until: datetime | None
    chunks: tuple[Chunk, ...]
    earlier: tuple[tuple[str, datetime | None], ...] = ()
    has_progress: bool = False

    @property
    def covers_history(self) -> bool:
        """The range starts at or before every event of the stream."""
        return self.start is not None and not self.earlier


def plan_backfill(
    source: HistorySource,
    stream: str,
    *,
    progress: Progress | None,
    now: datetime,
    start: datetime | None = None,
    end: datetime | None = None,
    chunk: timedelta = BACKFILL_CHUNK,
) -> BackfillPlan:
    """The chunked range to backfill for one stream, up to where its progress is settled.

    Reads the source but writes nothing.
    """
    if chunk <= timedelta(0):
        raise ValueError(f"chunk width must be positive: {chunk}")
    now = to_utc(now)
    settled = None if progress is None else progress.settled_until
    stop = now if settled is None else min(settled, now)
    if end is not None:
        stop = min(stop, to_utc(end))
    begin = source.history_start(stream) if start is None else to_utc(start)
    parts = source.parts(stream)
    has_progress = progress is not None
    if begin is None or begin >= stop:
        return BackfillPlan(stream, parts, begin, stop, settled, (), has_progress=has_progress)
    chunks: list[Chunk] = []
    edge = begin
    while edge < stop:
        chunks.append(Chunk(edge, min(edge + chunk, stop)))
        edge += chunk
    return BackfillPlan(
        stream,
        parts,
        begin,
        stop,
        settled,
        tuple(chunks),
        source.history_before(stream, begin),
        has_progress=has_progress,
    )


@dataclass(frozen=True)
class Planning:
    """Every stream's plan, or the failure that stopped planning."""

    plans: tuple[BackfillPlan, ...] = ()
    failure: StreamFailure | None = None


def plan_all_backfills(
    conn: sqlite3.Connection | None,
    source: HistorySource,
    *,
    now: datetime,
    start: datetime | None = None,
    end: datetime | None = None,
) -> Planning:
    """Plan every stream of the source from its stored progress, or from none without a database.

    Writes nothing.
    """
    plans: list[BackfillPlan] = []
    stream = None
    try:
        for stream in _distinct(source.streams()):
            progress = None if conn is None else get_progress(conn, stream)
            plans.append(
                plan_backfill(source, stream, progress=progress, now=now, start=start, end=end)
            )
    except (SourceUnavailable, sqlite3.Error) as exc:
        return Planning(failure=failure_of(stream, exc))
    return Planning(tuple(plans))


def _distinct(streams: Sequence[str]) -> list[str]:
    if len(set(streams)) != len(streams):
        raise ValueError(f"a stream is listed more than once: {list(streams)}")
    return list(streams)


class BackfillProgress(Enum):
    SET = "set"  # the last chunk's commit set the stream's first progress
    KEPT = "kept"  # the stream already had progress with a settled-until time
    KEPT_UNSETTLED = "kept unsettled"  # the stream already had progress without one
    NOT_COVERED = "not covered"  # the range starts after some of the stream's history
    SET_MEANWHILE = "set meanwhile"  # another ingest set the stream's progress first


@dataclass(frozen=True)
class ChunkDone:
    """One committed chunk of a stream's backfill.

    incomplete_from is where its unsettled events may begin, if any were held back.
    """

    stream: str
    index: int
    total: int
    chunk: Chunk
    inserted: int
    skipped: int
    held_back: int
    incomplete_from: datetime | None
    seconds: float


@dataclass
class BackfillResult:
    """Running totals of one stream's backfill, and how its progress ended up once it finishes.

    Every event starting before complete_until is stored.
    """

    plan: BackfillPlan
    chunks_done: int = 0
    inserted: int = 0
    skipped: int = 0
    held_back: int = 0
    seconds: float = 0.0
    incomplete: list[tuple[Chunk, datetime]] = field(default_factory=list[tuple[Chunk, datetime]])
    complete_until: datetime | None = None
    progress: BackfillProgress | None = None

    @property
    def stream(self) -> str:
        return self.plan.stream


@dataclass(frozen=True)
class BackfillRun:
    """The streams a backfill committed chunks for, and why it stopped early, if it did."""

    results: tuple[BackfillResult, ...]
    failure: StreamFailure | None = None
    interrupted: bool = False

    @property
    def ok(self) -> bool:
        return self.failure is None and not self.interrupted


def run_backfill(
    conn: sqlite3.Connection,
    source: HistorySource,
    plans: Sequence[BackfillPlan],
    *,
    clock: Clock | None = None,
    on_chunk: Callable[[ChunkDone], None] | None = None,
    on_stream: Callable[[BackfillResult], None] | None = None,
) -> BackfillRun:
    """Ingest every planned chunk, oldest first and each in its own commit, stopping at a failure.

    A stream's last commit also sets its first progress when the plan covers all its history.
    """
    _distinct([plan.stream for plan in plans])
    clock = clock or (lambda: datetime.now(UTC))
    project = projector_for([source])
    results: list[BackfillResult] = []
    stream = None
    total = sum(len(plan.chunks) for plan in plans)
    step = progress_step(total)
    began = clock()
    outcome = Outcome.CRASHED
    planned = [plan for plan in plans if plan.chunks]
    log.info(
        "backfill started",
        extra={
            "streams": [plan.stream for plan in planned],
            "chunks": total,
            "start": min((p.chunks[0].start for p in planned), default=began).isoformat(),
            "end": max((p.chunks[-1].end for p in planned), default=began).isoformat(),
        },
    )

    def chunk_done(done: ChunkDone) -> None:
        log.debug(
            "chunk committed",
            extra={
                "stream": done.stream,
                "chunk": done.index + 1,
                "chunks": done.total,
                "start": done.chunk.start.isoformat(),
                "inserted": done.inserted,
                "skipped": done.skipped,
                "held_back": done.held_back,
                "duration_ms": round(done.seconds * 1000),
            },
        )
        committed = sum(result.chunks_done for result in results)
        if committed % step == 0 and committed < total:
            log.info(
                "backfill progress",
                extra={
                    "chunks_done": committed,
                    "chunks": total,
                    "inserted": sum(result.inserted for result in results),
                },
            )
        if on_chunk is not None:
            on_chunk(done)

    try:
        for plan in plans:
            if not plan.chunks:
                continue
            stream = plan.stream
            results.append(BackfillResult(plan))
            _backfill_stream(conn, source, project, results[-1], clock, chunk_done)
            if on_stream is not None:
                on_stream(results[-1])
        outcome = Outcome.OK
    except (SourceUnavailable, sqlite3.Error, UnclaimedSource, StrayObservation) as exc:
        outcome = Outcome.FAILED
        log.exception("backfill failed", extra={"stream": stream})
        return BackfillRun(_committed(results), failure_of(stream, exc))
    except KeyboardInterrupt:
        outcome = Outcome.INTERRUPTED
        log.warning("backfill interrupted", extra={"stream": stream})
        return BackfillRun(_committed(results), interrupted=True)
    finally:
        log.info(
            "backfill finished",
            extra={
                "outcome": outcome.value,
                "chunks_done": sum(result.chunks_done for result in results),
                "chunks": total,
                "inserted": sum(result.inserted for result in results),
                "skipped": sum(result.skipped for result in results),
                "held_back": sum(result.held_back for result in results),
                "duration_ms": round((clock() - began).total_seconds() * 1000),
                "streams": {
                    result.stream: {
                        "chunks_done": result.chunks_done,
                        "inserted": result.inserted,
                        "progress": None if result.progress is None else result.progress.value,
                    }
                    for result in results
                },
            },
        )
    return BackfillRun(tuple(results))


def _committed(results: list[BackfillResult]) -> tuple[BackfillResult, ...]:
    return tuple(result for result in results if result.chunks_done)


def _backfill_stream(
    conn: sqlite3.Connection,
    source: HistorySource,
    project: Projector,
    result: BackfillResult,
    clock: Clock,
    on_chunk: Callable[[ChunkDone], None] | None,
) -> None:
    plan = result.plan
    attempt = not plan.has_progress and plan.covers_history
    first_incomplete: Pull | None = None
    last = len(plan.chunks) - 1
    for index, piece in enumerate(plan.chunks):
        now = clock()
        pulled = source.pull_range(plan.stream, piece.start, piece.end, now=now)
        incomplete_from = _incomplete_from(pulled, piece)
        if incomplete_from is not None and first_incomplete is None:
            first_incomplete = pulled
        complete = first_incomplete or pulled
        written = commit_pull(
            conn,
            plan.stream,
            pulled,
            project=project,
            now=now,
            progress_from=complete if index == last and attempt else None,
            only_if_none=True,
        )
        seconds = (clock() - now).total_seconds()
        result.chunks_done += 1
        result.inserted += written.inserted
        result.skipped += written.skipped
        result.held_back += pulled.held_back
        result.seconds += seconds
        if incomplete_from is not None:
            result.incomplete.append((piece, incomplete_from))
        if index == last:
            result.complete_until = result.incomplete[0][1] if result.incomplete else plan.end
            result.progress = _progress_outcome(plan, written.progress_moved)
        if on_chunk is not None:
            on_chunk(
                ChunkDone(
                    plan.stream,
                    index,
                    len(plan.chunks),
                    piece,
                    written.inserted,
                    written.skipped,
                    pulled.held_back,
                    incomplete_from,
                    seconds,
                )
            )


def _incomplete_from(pulled: Pull, piece: Chunk) -> datetime | None:
    if pulled.settled_until is None:
        return piece.start if pulled.held_back else None
    return pulled.settled_until if pulled.settled_until < piece.end else None


def _progress_outcome(plan: BackfillPlan, moved: bool) -> BackfillProgress:
    if plan.has_progress:
        return BackfillProgress.KEPT if plan.settled_until else BackfillProgress.KEPT_UNSETTLED
    if not plan.covers_history:
        return BackfillProgress.NOT_COVERED
    return BackfillProgress.SET if moved else BackfillProgress.SET_MEANWHILE
