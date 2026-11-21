from __future__ import annotations

import argparse
import logging
import sys
from functools import partial
from pathlib import Path

from computer_history.cli.db import db_busy_hint, store_unavailable
from computer_history.cli.sources import source_failed, unavailable_on
from computer_history.logs import desktop_notifier
from computer_history.sources import (
    POLL_INTERVAL_SECONDS,
    ActivityWatch,
    AWClient,
    CaptureSpool,
    CycleSummary,
    FailureKind,
    FailureStreak,
    IngestHealth,
    IngestOutcome,
    StreamFailure,
    health_path,
    poll,
    read_health,
    resolve_spool_path,
    watch,
    write_health,
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
            health = health_path(db_path)
            streak = FailureStreak(
                save=partial(write_health, health),
                notify=desktop_notifier(),
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
            try:
                watch(conn, sources, report=partial(log_cycle, streak=streak))
            except KeyboardInterrupt:
                log.info("stopped")
            return 0
        summary = poll(conn, sources)
    log_cycle(summary)
    return _print_summary(summary, f"{args.aw_url} and {spool_path}", db_path)


def log_cycle(
    summary: CycleSummary, delay: float | None = None, *, streak: FailureStreak | None = None
) -> None:
    """Write the cycle's one record, INFO if every stream committed and ERROR if not.

    Under a streak it counts the cycle, adds a traceback to its first failure and notes its end.
    """
    recovery = None if streak is None else streak.record(summary)
    fields: dict[str, object] = {
        "duration_ms": round(summary.seconds * 1000),
        "streams": {name: _counts(o) for name, o in summary.outcomes.items()},
    }
    if summary.ok:
        log.info("cycle ok: %s", cycle_line(summary) or "no streams", extra=fields)
    else:
        fields["failures"] = [
            {"stream": f.stream, "kind": f.kind.value, "error": f.error} for f in summary.failures
        ]
        if delay is not None:
            fields["retry_s"] = round(delay)
        if streak is not None:
            fields["streak"] = streak.failures
        first = streak is None or streak.failures == 1
        cause = next((f.exc for f in summary.failures if f.kind is not FailureKind.SOURCE), None)
        log.error(
            "cycle failed: %s",
            cycle_line(summary),
            extra=fields,
            exc_info=cause if first else None,
        )
    if recovery is not None:
        log.info(
            "ingest recovered",
            extra={
                "failed_cycles": recovery.failed_cycles,
                "down_since": recovery.down_since.isoformat(),
            },
        )


def _counts(outcome: IngestOutcome) -> dict[str, int]:
    return {
        "inserted": outcome.inserted,
        "skipped": outcome.skipped,
        "held_back": outcome.held_back,
        "rejected": outcome.rejected,
    }


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
