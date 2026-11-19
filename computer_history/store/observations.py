"""The single write path for raw data: observations, their signals, ingest progress."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NamedTuple

from computer_history.store.db import transaction
from computer_history.store.progress import ProgressUpdate, write_with_batch
from computer_history.store.signals import Projector, SignalRow, write_signals
from computer_history.store.timefmt import utc_iso


@dataclass(frozen=True)
class Observation:
    """One raw source event. payload is the source's JSON, stored verbatim."""

    source: str
    source_id: str
    started_at: datetime | str
    ended_at: datetime | str
    payload: str


class InsertResult(NamedTuple):
    inserted: int
    skipped: int
    progress_moved: bool = False


_INSERT_OBSERVATION = """
INSERT INTO observations (source, source_id, started_at, ended_at, payload, ingested_at)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (source, source_id) DO NOTHING
"""


def insert_observations(
    conn: sqlite3.Connection,
    observations: Iterable[Observation],
    *,
    project: Projector,
    progress: ProgressUpdate | None = None,
    now: datetime | None = None,
) -> InsertResult:
    """Atomically write a batch of observations, their signals and optionally the source's progress.

    Only new observations are projected, and the write is stamped with now.
    """
    if conn.in_transaction:
        raise RuntimeError(
            "insert_observations opens its own transaction; "
            "it must not be called inside transaction()"
        )
    rows = [_prepare(observation) for observation in observations]
    ingested_at = utc_iso(datetime.now(UTC) if now is None else now)
    inserted = 0
    signals: list[SignalRow] = []
    with transaction(conn):
        for source, source_id, started, ended, payload in rows:
            result = conn.execute(
                _INSERT_OBSERVATION, (source, source_id, started, ended, payload, ingested_at)
            )
            if result.rowcount == 0:
                continue
            inserted += 1
            signal = project(source, payload)
            if signal is not None:
                signals.append((result.lastrowid, source, started, ended, signal))
        write_signals(conn, signals)
        moved = progress is not None and write_with_batch(conn, progress, advanced_at=ingested_at)
    return InsertResult(inserted=inserted, skipped=len(rows) - inserted, progress_moved=moved)


def _prepare(observation: Observation) -> tuple[str, str, str, str, str]:
    if not observation.source:
        raise ValueError(f"observation {observation.source_id!r} has no source")
    if not observation.source_id:
        raise ValueError(f"observation from {observation.source!r} has no source_id")
    started = utc_iso(observation.started_at)
    ended = utc_iso(observation.ended_at)
    if ended < started:
        raise ValueError(
            f"observation {observation.source}/{observation.source_id} ends before it starts"
        )
    return observation.source, observation.source_id, started, ended, observation.payload
