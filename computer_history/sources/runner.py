"""The ingest runner: polls every stream of every source, once or on a fixed interval."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import NoReturn

from computer_history.sources.commit import (
    FailureKind,
    StrayObservation,
    StreamFailure,
    commit_pull,
    failure_of,
)
from computer_history.sources.contract import Source, SourceUnavailable
from computer_history.sources.projection import projector_for
from computer_history.store import Projector, UnclaimedSource, get_progress

__all__ = [
    "POLL_INTERVAL_SECONDS",
    "CycleSummary",
    "IngestOutcome",
    "poll",
    "watch",
]

POLL_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class IngestOutcome:
    """What one poll wrote for a stream: every event before settled_until is now stored."""

    inserted: int
    skipped: int
    held_back: int
    settled_until: datetime | None


@dataclass(frozen=True)
class CycleSummary:
    """One poll's outcomes for the streams that committed, and the failures that cut it short."""

    at: datetime
    outcomes: dict[str, IngestOutcome] = field(default_factory=dict)
    failures: tuple[StreamFailure, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.failures


def poll(
    conn: sqlite3.Connection, sources: Sequence[Source], *, now: datetime | None = None
) -> CycleSummary:
    """Poll every stream of every source once, each stream in its own commit.

    An unavailable source skips the rest of its streams, a busy database ends the cycle, and a
    stream whose observations cannot be projected is skipped.
    """
    at = datetime.now(UTC) if now is None else now
    project = projector_for(sources)
    outcomes: dict[str, IngestOutcome] = {}
    failures: list[StreamFailure] = []
    seen: set[str] = set()
    for source in sources:
        stream = None
        try:
            streams = list(source.streams())
            _claim(seen, streams)
            for stream in streams:
                try:
                    outcomes[stream] = _poll_stream(conn, source, stream, project, now=at)
                except (UnclaimedSource, StrayObservation) as exc:
                    failures.append(failure_of(stream, exc))
        except (SourceUnavailable, sqlite3.Error) as exc:
            failure = failure_of(stream, exc)
            if failure.kind is FailureKind.DATABASE:
                raise
            failures.append(failure)
            if failure.kind is FailureKind.DATABASE_BUSY:
                break
    return CycleSummary(at, outcomes, tuple(failures))


def _claim(seen: set[str], streams: list[str]) -> None:
    """Record the streams, refusing one that another source already feeds."""
    for stream in streams:
        if stream in seen:
            raise ValueError(f"stream {stream!r} is fed by more than one source")
        seen.add(stream)


def _poll_stream(
    conn: sqlite3.Connection, source: Source, stream: str, project: Projector, *, now: datetime
) -> IngestOutcome:
    progress = get_progress(conn, stream)
    pulled = source.pull_after(stream, None if progress is None else progress.position, now=now)
    written = commit_pull(conn, stream, pulled, project=project, now=now, progress_from=pulled)
    return IngestOutcome(written.inserted, written.skipped, pulled.held_back, pulled.settled_until)


def watch(
    conn: sqlite3.Connection,
    sources: Sequence[Source],
    *,
    report: Callable[[CycleSummary, float], None],
    interval: float = POLL_INTERVAL_SECONDS,
    clock: Callable[[], datetime] | None = None,
    monotonic: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> NoReturn:
    """Poll forever, reporting each cycle and the seconds until the next one.

    A failed cycle is reported like any other and retried on the next.
    """
    clock = clock or (lambda: datetime.now(UTC))
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    while True:
        began = monotonic()
        summary = poll(conn, sources, now=clock())
        delay = max(0.0, interval - (monotonic() - began))
        report(summary, delay)
        sleep(delay)
