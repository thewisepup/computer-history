"""The orchestrator: pull every bucket of a source and write the results."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import NamedTuple

from computer_history.sources.activitywatch.client import AWApi
from computer_history.sources.activitywatch.discovery import AWSource, discover_sources
from computer_history.sources.activitywatch.pull import _now, pull_bucket
from computer_history.store import Cursor, get_cursor, insert_observations, to_utc

CURSOR_OVERLAP_SECONDS = 600


class IngestOutcome(NamedTuple):
    """What one ingest_source call did.

    held_back counts events that have not settled yet. frontier is how far
    the pull reached: every event starting before it is now stored.
    """

    inserted: int
    skipped: int
    held_back: int
    frontier: datetime | None


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

    With no explicit range this is an incremental poll: it reads from just
    before the cursor and advances it. An explicit range (used by backfill)
    leaves the cursor alone. If any bucket's pull fails, nothing is written.
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


def ingest_all(
    conn: sqlite3.Connection, client: AWApi, *, now: datetime | None = None
) -> dict[str, IngestOutcome]:
    """One incremental poll of every discovered source, keyed by source name.

    Each source commits on its own.
    """
    now = _now(now)
    return {
        source.name: ingest_source(conn, client, source, now=now)
        for source in discover_sources(client)
    }
