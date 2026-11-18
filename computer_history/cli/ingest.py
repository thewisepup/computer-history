"""The ingest command: one poll, or the --watch loop."""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from computer_history.cli.shared import db_busy_hint, open_store
from computer_history.sources import (
    AWApi,
    AWClient,
    AWError,
    IngestOutcome,
    discover_sources,
    ingest_source,
)
from computer_history.store import resolve_db_path

log = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class CycleSummary:
    """What one poll cycle did: the outcomes of the sources that committed and,
    if the cycle stopped early, why and on which source."""

    at: datetime
    outcomes: dict[str, IngestOutcome] = field(default_factory=dict)
    error: str | None = None
    failed_source: str | None = None
    database_error: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None

    def line(self) -> str:
        done = "; ".join(
            f"{name} +{o.inserted} ({o.skipped} dup, {o.held_back} held)"
            for name, o in self.outcomes.items()
        )
        if self.error is None:
            return done or "no ActivityWatch sources found"
        where = f" on {self.failed_source}" if self.failed_source else ""
        failure = f"ingest failed{where}: {self.error}"
        return f"{done}; then {failure}" if done else failure


def run_cycle(
    conn: sqlite3.Connection, client: AWApi, *, now: datetime | None = None
) -> CycleSummary:
    """One incremental poll of every source. Never raises for a transient failure.

    An unreachable ActivityWatch or a locked database ends the cycle and is
    reported in the summary. Sources that committed before it stay committed.
    """
    at = datetime.now(UTC) if now is None else now
    outcomes: dict[str, IngestOutcome] = {}
    current: str | None = None
    try:
        for source in discover_sources(client):
            current = source.name
            outcomes[source.name] = ingest_source(conn, client, source, now=at)
    except AWError as exc:
        return CycleSummary(at, outcomes, error=str(exc), failed_source=current)
    except sqlite3.OperationalError as exc:
        return CycleSummary(
            at,
            outcomes,
            error=f"database error: {exc}",
            failed_source=current,
            database_error=True,
        )
    return CycleSummary(at, outcomes)


def watch(
    conn: sqlite3.Connection,
    client: AWApi,
    *,
    interval: float = POLL_INTERVAL_SECONDS,
    sleep: Callable[[float], None] | None = None,
) -> None:
    """Poll forever (until Ctrl-C), one logged line per cycle.

    A transient failure is logged and retried next cycle.
    """
    sleep = time.sleep if sleep is None else sleep
    while True:
        began = time.monotonic()
        summary = run_cycle(conn, client)
        delay = max(0.0, interval - (time.monotonic() - began))
        if summary.ok:
            log.info(summary.line())
        else:
            log.warning("%s; retrying in %.0fs", summary.line(), delay)
        sleep(delay)


def cmd_ingest(args: argparse.Namespace) -> int:
    db_path = resolve_db_path(args.db_path)
    client = AWClient(args.aw_url)
    conn = open_store(db_path)
    if conn is None:
        return 1
    try:
        if args.watch:
            log.info(
                "watching %s every %ds into %s (Ctrl-C to stop)",
                args.aw_url,
                POLL_INTERVAL_SECONDS,
                db_path,
            )
            try:
                watch(conn, client)
            except KeyboardInterrupt:
                log.info("stopped")
            return 0
        summary = run_cycle(conn, client)
    finally:
        conn.close()
    if summary.outcomes or summary.ok:
        print(f"Ingested from {args.aw_url} into {db_path}")
    if summary.ok and not summary.outcomes:
        print("  no ActivityWatch sources found (no window, AFK or web buckets)")
    width = max((len(name) for name in summary.outcomes), default=0)
    for name, o in summary.outcomes.items():
        print(
            f"  {name:<{width}}  inserted {o.inserted:>6,}  skipped {o.skipped:>6,}"
            f"  held back {o.held_back:>3,}"
        )
    if summary.ok:
        return 0
    where = f" on {summary.failed_source}" if summary.failed_source else ""
    print(f"error{where}: {summary.error}", file=sys.stderr)
    if summary.database_error:
        print(db_busy_hint(db_path), file=sys.stderr)
    else:
        print("Is ActivityWatch running? Check with `computer-history status`.", file=sys.stderr)
    return 1
