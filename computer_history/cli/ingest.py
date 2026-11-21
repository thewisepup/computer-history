from __future__ import annotations

import argparse
import logging
import sys
from functools import partial
from pathlib import Path

from computer_history.alerts import desktop_notifier
from computer_history.cli.db import db_busy_hint, store_unavailable
from computer_history.cli.sources import source_failed, unavailable_on
from computer_history.sources import (
    POLL_INTERVAL_SECONDS,
    ActivityWatch,
    AWClient,
    CaptureSpool,
    CycleReporter,
    CycleSummary,
    FailureKind,
    FailureStreak,
    IngestHealth,
    IngestOutcome,
    StreakAlert,
    StreamFailure,
    backend_heartbeat_path,
    health_path,
    poll,
    read_health,
    resolve_spool_path,
    watch,
    write_health,
)
from computer_history.store import Purpose, SpoolHold, open_store

log = logging.getLogger(__name__)


def cmd_ingest(args: argparse.Namespace) -> int:
    db_path: Path = args.database
    spool_path = resolve_spool_path(args.spool_path, db_path, args.profile)
    hold = SpoolHold.beside(db_path)
    sources = [ActivityWatch(AWClient(args.aw_url)), CaptureSpool(spool_path, hold=hold)]
    store = open_store(db_path, Purpose.WRITE)
    conn = store.conn
    if conn is None:
        return store_unavailable(store)
    with store:
        if args.watch:
            health = health_path(db_path)
            post = desktop_notifier()
            streak = FailureStreak(
                save=partial(write_health, health),
                notify=None if post is None else lambda alert: post(alert_text(alert)),
                health=_saved(health),
            )
            log.info(
                "watching (Ctrl-C to stop)",
                extra={
                    "aw_url": args.aw_url,
                    "spool": str(spool_path),
                    "db": str(db_path),
                    "interval_s": POLL_INTERVAL_SECONDS,
                },
            )
            if hold.active:
                log.info("spool files are kept until a cycle is ok (%s is there)", hold.path)
            try:
                watch(
                    conn,
                    sources,
                    report=CycleReporter(cycle_line, streak=streak),
                    heartbeat=backend_heartbeat_path(db_path),
                    hold=hold,
                )
            except KeyboardInterrupt:
                log.info("stopped")
            return 0
        summary = poll(conn, sources)
    CycleReporter(cycle_line, shown=True)(summary)
    code = _print_summary(summary, f"{args.aw_url} and {spool_path}", db_path)
    if hold.active:
        print(f"  spool files kept: {hold.path} holds their deletion while an update runs")
    return code


def alert_text(alert: StreakAlert) -> str:
    if alert.ended:
        return "ingest recovered."
    return f"ingest failing for {alert.failures:,} cycles. Run `computer-history status`."


def _saved(path: Path) -> IngestHealth | None:
    try:
        return read_health(path)
    except (OSError, ValueError) as exc:
        log.warning("ingest health unreadable, starting afresh", extra={"error": str(exc)})
        return None


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
    if failure.kind is FailureKind.SOURCE:
        return unavailable_on(failure.stream)
    return f" on {failure.stream}" if failure.stream else ""


def _reason(failure: StreamFailure) -> str:
    if failure.kind in (FailureKind.SOURCE, FailureKind.ADAPTER):
        return failure.error
    return f"database error: {failure.error}"
