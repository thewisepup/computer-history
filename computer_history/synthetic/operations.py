"""What the product does to a database, run on a cached dataset so the cost meter can count it."""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import NamedTuple
from zoneinfo import ZoneInfo

from computer_history.sources import AX_TEXT_SOURCE, capture_health, reproject_signals
from computer_history.store import (
    MIN_GAP_SECONDS,
    STATUS_WINDOW,
    connect,
    find_gaps,
    recent_span,
    source_summary,
    table_counts,
    to_utc,
)
from computer_history.synthetic.activitywatch import HOST
from computer_history.synthetic.build import (
    DATABASE_NAME,
    SETTLE_AFTER,
    backfill_feeds,
    poll_feeds,
    render_sources,
)
from computer_history.synthetic.cache import CachedDataset, open_cached
from computer_history.synthetic.generate import DatasetInputs, generate_timeline
from computer_history.synthetic.meter import Costs, measure
from computer_history.synthetic.timeline import local_midnight


@dataclass(frozen=True)
class GateDataset:
    """A cached dataset the gate measures, and the moment just after its range it settled at."""

    inputs: DatasetInputs
    entry: CachedDataset
    now: datetime
    observations: int


def gate_dataset(inputs: DatasetInputs, entry: CachedDataset) -> GateDataset:
    """The gate's view of a cache entry, read from its manifest."""
    manifest = json.loads(entry.manifest_path.read_text(encoding="utf-8"))
    now = to_utc(manifest["end"]) + SETTLE_AFTER
    return GateDataset(inputs, entry, now, sum(manifest["observations"].values()))


class Session(NamedTuple):
    conn: sqlite3.Connection
    action: Callable[[], object]


@dataclass(frozen=True)
class Operation:
    """One thing the product does: how to start it on a dataset in a scratch folder."""

    name: str
    start: Callable[[GateDataset, Path], Session]
    fresh: bool = False
    writes: bool = False
    windowed: bool = False


def measure_operation(operation: Operation, dataset: GateDataset, folder: Path) -> Costs:
    """Run the operation once uncounted, then once under the cost meter, in a scratch folder.

    The folder is removed afterwards, and a fresh run's warm copy before the counted one starts.
    """
    try:
        warm = operation.start(dataset, folder / "warm")
        try:
            warm.action()
            if not operation.fresh:
                return measure(warm.conn, warm.action)
        finally:
            warm.conn.close()
        shutil.rmtree(folder / "warm", ignore_errors=True)
        measured = operation.start(dataset, folder / "measured")
        try:
            return measure(measured.conn, measured.action)
        finally:
            measured.conn.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def _ingest(dataset: GateDataset, folder: Path) -> Session:
    timeline = generate_timeline(dataset.inputs)
    rendered = render_sources(timeline, dataset.inputs.seed)
    feeds = tuple(source.feed(folder) for source in rendered.values())
    conn = connect(folder / DATABASE_NAME)

    def ingest() -> None:
        backfill_feeds(conn, feeds, start=timeline.start, now=dataset.now)
        poll_feeds(conn, feeds, now=dataset.now)

    return Session(conn, ingest)


def _rebuild_signals(dataset: GateDataset, folder: Path) -> Session:
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(dataset.entry.db_path, folder / DATABASE_NAME)
    conn = connect(folder / DATABASE_NAME)
    return Session(conn, lambda: reproject_signals(conn))


def _status_reads(dataset: GateDataset, folder: Path) -> Session:
    conn = open_cached(dataset.entry)

    def status_reads() -> None:
        for summary in source_summary(conn):
            span = recent_span(summary, STATUS_WINDOW)
            if summary.source != AX_TEXT_SOURCE and span is not None and span[0] < span[1]:
                find_gaps(conn, summary.source, *span, min_gap_seconds=MIN_GAP_SECONDS)
        table_counts(conn)

    return Session(conn, status_reads)


def _capture_health(dataset: GateDataset, folder: Path) -> Session:
    spool = folder / "spool"
    spool.mkdir(parents=True, exist_ok=True)
    conn = open_cached(dataset.entry)
    summaries = source_summary(conn)
    zone = ZoneInfo(dataset.inputs.timezone)
    day_start = local_midnight(dataset.now.astimezone(zone).date(), zone)
    return Session(
        conn,
        lambda: capture_health(
            conn,
            summaries,
            spool,
            None,
            now=dataset.now,
            window=STATUS_WINDOW,
            hostname=HOST,
            min_gap_seconds=MIN_GAP_SECONDS,
            day_start=day_start,
        ),
    )


OPERATIONS: Mapping[str, Operation] = MappingProxyType(
    {
        operation.name: operation
        for operation in (
            Operation("ingest", _ingest, fresh=True, writes=True),
            Operation("rebuild-signals", _rebuild_signals, writes=True),
            Operation("status-reads", _status_reads, windowed=True),
            Operation("capture-health", _capture_health, windowed=True),
        )
    }
)
