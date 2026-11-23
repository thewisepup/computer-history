"""What the product does to a database, run on a cached dataset so the cost meter can count it."""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import NamedTuple
from zoneinfo import ZoneInfo

from computer_history.sources import (
    SCREENSHOT_SOURCE,
    WINDOW_TEXT_SOURCE,
    capture_health,
    reproject_signals,
    screenshot_health,
)
from computer_history.store import (
    MIN_GAP_SECONDS,
    STATUS_WINDOW,
    connect,
    source_summary,
    status_reads,
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


@contextmanager
def started(
    operation: Operation, dataset: GateDataset, folder: Path
) -> Generator[Session, None, None]:
    """The operation started in a scratch folder, closed and its folder removed afterwards."""
    try:
        session = operation.start(dataset, folder)
        try:
            yield session
        finally:
            session.conn.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def measure_operation(operation: Operation, dataset: GateDataset, folder: Path) -> Costs:
    """Run the operation under the cost meter in a scratch folder, removed afterwards.

    A fresh operation is counted on its only run; any other runs once uncounted first, so the
    counted run finds its connection warm.
    """
    try:
        with started(operation, dataset, folder / "run") as session:
            if not operation.fresh:
                session.action()
            return measure(session.conn, session.action)
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
    skip = {SCREENSHOT_SOURCE, WINDOW_TEXT_SOURCE}
    return Session(conn, lambda: status_reads(conn, source_summary(conn), skip=skip))


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


def _screenshot_health(dataset: GateDataset, folder: Path) -> Session:
    conn = open_cached(dataset.entry)
    zone = ZoneInfo(dataset.inputs.timezone)
    day_start = local_midnight(dataset.now.astimezone(zone).date(), zone)
    return Session(conn, lambda: screenshot_health(conn, day_start=day_start, now=dataset.now))


OPERATIONS: Mapping[str, Operation] = MappingProxyType(
    {
        operation.name: operation
        for operation in (
            Operation("ingest", _ingest, fresh=True, writes=True),
            Operation("rebuild-signals", _rebuild_signals, fresh=True, writes=True),
            Operation("status-reads", _status_reads, windowed=True),
            Operation("capture-health", _capture_health, windowed=True),
            Operation("screenshot-health", _screenshot_health, windowed=True),
        )
    }
)
