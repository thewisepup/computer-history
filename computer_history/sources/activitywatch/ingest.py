"""The orchestrator: pull every bucket of a source and write the results."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import NamedTuple

from computer_history.sources.activitywatch.client import AWApi
from computer_history.sources.activitywatch.discovery import AWSource, discover_sources
from computer_history.sources.activitywatch.position import progress_at, resume_start
from computer_history.sources.activitywatch.pull import SourcePull, pull_source, resolve_now
from computer_history.store import (
    InsertResult,
    get_progress,
    insert_observations,
)


class IngestOutcome(NamedTuple):
    """What one ingest_source call did: every event starting before the
    frontier is now stored, and held_back counts events not settled yet."""

    inserted: int
    skipped: int
    held_back: int
    frontier: datetime | None


def outcome_of(pulled: SourcePull, written: InsertResult) -> IngestOutcome:
    """The ingest outcome of a pull once its events have been written."""
    return IngestOutcome(written.inserted, written.skipped, pulled.held_back, pulled.frontier)


def ingest_source(
    conn: sqlite3.Connection,
    client: AWApi,
    source: AWSource,
    *,
    start: datetime | str | None = None,
    end: datetime | str | None = None,
    now: datetime | None = None,
) -> IngestOutcome:
    """Pull one source's buckets and write the batch and its progress together.

    With no explicit range it polls from just before the stored position and
    advances it; an explicit range leaves the progress alone.
    """
    incremental = start is None and end is None
    if incremental:
        progress = get_progress(conn, source.name)
        if progress is not None:
            start = resume_start(progress.position)
    pulled = pull_source(client, source, start=start, end=end, now=now)
    advance = (
        progress_at(source.name, pulled.frontier)
        if incremental and pulled.frontier is not None
        else None
    )
    return outcome_of(pulled, insert_observations(conn, pulled.observations, progress=advance))


def ingest_all(
    conn: sqlite3.Connection, client: AWApi, *, now: datetime | None = None
) -> dict[str, IngestOutcome]:
    """One incremental poll of every discovered source, keyed by source name.

    Each source commits on its own.
    """
    now = resolve_now(now)
    return {
        source.name: ingest_source(conn, client, source, now=now)
        for source in discover_sources(client)
    }
