"""The ingest command: one poll, or the --watch loop."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from computer_history.cli.db import db_busy_hint, store_unavailable
from computer_history.cli.sources import source_failed
from computer_history.sources import (
    POLL_INTERVAL_SECONDS,
    ActivityWatch,
    AWClient,
    CaptureSpool,
    CycleSummary,
    FailureKind,
    IngestOutcome,
    StreamFailure,
    poll,
    resolve_spool_path,
    watch,
)
from computer_history.store import Purpose, open_store, resolve_db_path

log = logging.getLogger(__name__)


def cmd_ingest(args: argparse.Namespace) -> int:
    db_path = resolve_db_path(args.db_path)
    spool_path = resolve_spool_path(args.spool_path, db_path)
    sources = [ActivityWatch(AWClient(args.aw_url)), CaptureSpool(spool_path)]
    store = open_store(db_path, Purpose.WRITE)
    conn = store.conn
    if conn is None:
        return store_unavailable(store)
    with store:
        if args.watch:
            log.info(
                "watching %s and %s every %ds into %s (Ctrl-C to stop)",
                args.aw_url,
                spool_path,
                POLL_INTERVAL_SECONDS,
                db_path,
            )
            try:
                watch(conn, sources, report=log_cycle)
            except KeyboardInterrupt:
                log.info("stopped")
            return 0
        summary = poll(conn, sources)
    return _print_summary(summary, f"{args.aw_url} and {spool_path}", db_path)


def log_cycle(summary: CycleSummary, delay: float) -> None:
    """Log one watch cycle as a single line."""
    if summary.ok:
        log.info(cycle_line(summary))
    else:
        log.warning("%s; retrying in %.0fs", cycle_line(summary), delay)


def cycle_line(summary: CycleSummary) -> str:
    done = "; ".join(
        f"{name} +{o.inserted} ({o.skipped} dup, {o.held_back} held{_rejected(o, ', ')})"
        for name, o in summary.outcomes.items()
    )
    if summary.ok:
        return done
    failed = "; ".join(
        f"ingest failed{_on(failure)}: {_reason(failure)}" for failure in summary.failures
    )
    return f"{done}; then {failed}" if done else failed


def _print_summary(summary: CycleSummary, read_from: str, db_path: Path) -> int:
    if summary.outcomes or summary.ok:
        print(f"Ingested from {read_from} into {db_path}")
    if summary.ok and set(summary.outcomes).isdisjoint(ActivityWatch.projectors):
        print("  no ActivityWatch sources found (no window, AFK or web buckets)")
    width = max((len(name) for name in summary.outcomes), default=0)
    for name, o in summary.outcomes.items():
        print(
            f"  {name:<{width}}  inserted {o.inserted:>6,}  skipped {o.skipped:>6,}"
            f"  held back {o.held_back:>3,}{_rejected(o, '  ')}"
        )
    for failure in summary.failures:
        if failure.kind is FailureKind.SOURCE:
            source_failed(failure.error, stream=failure.stream)
            continue
        print(f"error{_on(failure)}: {_reason(failure)}", file=sys.stderr)
        if failure.kind is not FailureKind.ADAPTER:
            print(db_busy_hint(db_path), file=sys.stderr)
    return 0 if summary.ok else 1


def _rejected(outcome: IngestOutcome, separator: str) -> str:
    return f"{separator}rejected {outcome.rejected:,}" if outcome.rejected else ""


def _on(failure: StreamFailure) -> str:
    return f" on {failure.stream}" if failure.stream else ""


def _reason(failure: StreamFailure) -> str:
    if failure.kind in (FailureKind.SOURCE, FailureKind.ADAPTER):
        return failure.error
    return f"database error: {failure.error}"
