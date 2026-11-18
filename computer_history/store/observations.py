"""The single write path for raw data: observations, their signals, the cursor."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NamedTuple

from computer_history.store.cursors import set_cursor
from computer_history.store.db import transaction
from computer_history.store.timefmt import utc_iso


@dataclass(frozen=True)
class Signal:
    """One observation's normalized, queryable fields. extras is a JSON string."""

    app: str | None = None
    domain: str | None = None
    url: str | None = None
    title: str | None = None
    text: str | None = None
    extras: str | None = None


@dataclass(frozen=True)
class Observation:
    """One raw source event, plus its signal if it has content.

    payload is the source's JSON, stored verbatim.
    """

    source: str
    source_id: str
    started_at: datetime | str
    ended_at: datetime | str
    payload: str
    signal: Signal | None = None


class Cursor(NamedTuple):
    source: str
    last_seen: datetime | str


class InsertResult(NamedTuple):
    inserted: int
    skipped: int


_INSERT_OBSERVATION = """
INSERT INTO observations (source, source_id, started_at, ended_at, payload, ingested_at)
VALUES (?, ?, ?, ?, ?, ?)
ON CONFLICT (source, source_id) DO NOTHING
"""

INSERT_SIGNAL = """
INSERT INTO signals
  (observation_id, source, started_at, ended_at, app, domain, url, title, text, extras)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def insert_observations(
    conn: sqlite3.Connection,
    observations: Iterable[Observation],
    *,
    advance_cursor: Cursor | None = None,
) -> InsertResult:
    """Write a batch of observations, their signals, and optionally a cursor, atomically.

    Observations already stored are skipped, along with their signals.
    """
    if conn.in_transaction:
        raise RuntimeError(
            "insert_observations opens its own transaction; "
            "it must not be called inside transaction()"
        )
    rows = [_prepare(observation) for observation in observations]
    cursor = (
        None
        if advance_cursor is None
        else Cursor(advance_cursor.source, utc_iso(advance_cursor.last_seen))
    )
    ingested_at = utc_iso(datetime.now(UTC))
    inserted = 0
    with transaction(conn):
        for source, source_id, started, ended, payload, signal in rows:
            result = conn.execute(
                _INSERT_OBSERVATION, (source, source_id, started, ended, payload, ingested_at)
            )
            if result.rowcount == 0:
                continue
            inserted += 1
            if signal is not None:
                conn.execute(
                    INSERT_SIGNAL, signal_params(result.lastrowid, source, started, ended, signal)
                )
        if cursor is not None:
            set_cursor(conn, cursor.source, cursor.last_seen)
    return InsertResult(inserted=inserted, skipped=len(rows) - inserted)


def signal_params(
    observation_id: int, source: str, started_at: str, ended_at: str, signal: Signal
) -> tuple[int | str | None, ...]:
    """The insert parameters for one signal row. Also used by rebuild_signals."""
    return (
        observation_id,
        source,
        started_at,
        ended_at,
        signal.app,
        signal.domain,
        signal.url,
        signal.title,
        signal.text,
        signal.extras,
    )


def _prepare(observation: Observation) -> tuple[str, str, str, str, str, Signal | None]:
    """Validate one observation and convert its timestamps."""
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
    return (
        observation.source,
        observation.source_id,
        started,
        ended,
        observation.payload,
        observation.signal,
    )
