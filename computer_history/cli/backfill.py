from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from computer_history.cli.db import db_busy_hint, store_unavailable
from computer_history.cli.formatting import duration, when
from computer_history.cli.sources import source_failed
from computer_history.sources import (
    BACKFILL_CHUNK,
    BackfillPlan,
    BackfillProgress,
    BackfillResult,
    Chunk,
    ChunkDone,
    FailureKind,
    StreamFailure,
    plan_all_backfills,
    run_backfill,
)
from computer_history.sources.activitywatch import ActivityWatch, AWClient
from computer_history.store import (
    Purpose,
    StoreState,
    open_store,
)


def cmd_backfill(args: argparse.Namespace) -> int:
    db_path: Path = args.database
    source = ActivityWatch(AWClient(args.aw_url))
    now = datetime.now(UTC)
    if args.start is not None and args.end is not None and args.start >= args.end:
        print("--start must be before --end", file=sys.stderr)
        return 2
    store = open_store(db_path, Purpose.READ if args.dry_run else Purpose.WRITE_EXISTING)
    if store.conn is None and store.state is not StoreState.MISSING:
        return store_unavailable(store)
    with store:
        planning = plan_all_backfills(store.conn, source, now=now, start=args.start, end=args.end)
        if planning.failure is not None:
            return _failed(planning.failure, f"cannot read {db_path}")
        plans = list(planning.plans)
        if not plans:
            print("no ActivityWatch sources found (no window, AFK or web buckets)")
            return 0
        verb = "Dry run: would backfill" if args.dry_run else "Backfilling"
        width = duration(BACKFILL_CHUNK.total_seconds())
        print(f"{verb} {args.aw_url} into {db_path} ({width} chunks)", flush=True)
        for plan in plans:
            _print_plan(plan, list_chunks=args.dry_run)
        if args.dry_run:
            print("dry run: nothing written")
            return 0
        if store.conn is not None:
            return _backfill(store.conn, source, plans, db_path)
    with open_store(db_path, Purpose.WRITE) as created:
        if created.conn is None:
            return store_unavailable(created)
        return _backfill(created.conn, source, plans, db_path)


def _backfill(
    conn: sqlite3.Connection, source: ActivityWatch, plans: list[BackfillPlan], db_path: Path
) -> int:
    run = run_backfill(conn, source, plans, on_chunk=_print_chunk, on_stream=_print_done)
    if run.ok:
        print()
        _print_backfill_totals(run.results)
        return 0
    _print_backfill_totals(run.results)
    if run.failure is None:
        print("backfill interrupted", file=sys.stderr)
        code = 130
    else:
        busy = db_busy_hint(db_path)
        code = _failed(run.failure, "backfill stopped: database error", busy_hint=busy)
    if run.results:
        print(_RESUME_HINT, file=sys.stderr)
    return code


_RESUME_HINT = (
    "Committed chunks are kept; re-run `computer-history backfill` to finish"
    " (done chunks only produce duplicates)."
)


def _print_chunk(done: ChunkDone) -> None:
    if done.index == 0:
        print(flush=True)
    width = len(str(done.total))
    line = (
        f"  {done.stream} chunk {done.index + 1:>{width}}/{done.total}  {_span(done.chunk)}"
        f"  inserted {done.inserted:>6,}  skipped {done.skipped:>6,}"
        f"  held back {done.held_back:>3,}  ({done.seconds:.1f}s)"
    )
    if done.incomplete_from is not None:
        line += f"  incomplete from {when(done.incomplete_from)}"
    print(line, flush=True)


def _print_done(result: BackfillResult) -> None:
    plan = result.plan
    print(
        f"  {result.stream} done in {duration(result.seconds)}:"
        f" inserted {result.inserted:,}, skipped {result.skipped:,},"
        f" held back {result.held_back:,}",
        flush=True,
    )
    later = (
        "`computer-history ingest` picks them up once settled"
        if not plan.has_progress
        else "re-run backfill later to fill them"
    )
    for chunk, frontier in result.incomplete:
        print(
            f"  note: {result.stream} events from {when(frontier)} to {when(chunk.end)}"
            f" had not settled yet (held back); {later}"
        )
    print(f"  {_progress_note(result)}")


def _progress_note(result: BackfillResult) -> str:
    match result.progress:
        case BackfillProgress.SET:
            return (
                f"progress set: settled until {when(result.complete_until)};"
                " `computer-history ingest` continues from there without re-reading history"
            )
        case BackfillProgress.KEPT:
            return (
                f"progress unchanged: settled until {when(result.plan.settled_until)}"
                " (incremental ingest owns what follows)"
            )
        case BackfillProgress.KEPT_UNSETTLED:
            return "progress unchanged: it has no settled-until time (incremental ingest owns it)"
        case BackfillProgress.NOT_COVERED:
            return (
                "progress not set: this range does not start before all of the source's"
                " history, so the next `ingest` reads from the beginning"
            )
        case BackfillProgress.NO_POSITION:
            return "progress not set: the source reported no position to resume from"
        case BackfillProgress.SET_MEANWHILE | None:
            return "progress not set: another ingest set it meanwhile"


def _print_plan(plan: BackfillPlan, *, list_chunks: bool) -> None:
    name = plan.stream
    buckets = len(plan.parts)
    head = f"  {name} ({buckets} bucket{'s' if buckets != 1 else ''}):"
    if plan.settled_until is not None:
        bound = f"up to its settled-until time {when(plan.settled_until)}"
    elif plan.has_progress:
        bound = "up to now (its ingest progress has no settled-until time)"
    else:
        bound = "up to now (no ingest progress yet)"
    if plan.start is None:
        print(
            f"{head} cannot tell where its history begins (no bucket has a usable"
            " 'created' time); pass --start"
        )
        return
    if not plan.chunks:
        print(f"{head} nothing to backfill: {when(plan.start)} is not before {when(plan.end)}")
        return
    count = len(plan.chunks)
    print(
        f"{head} {_span(Chunk(plan.start, plan.end))} {bound},"
        f" {count} chunk{'s' if count != 1 else ''}",
        flush=True,
    )
    for part, began in plan.earlier:
        newest = "has an unreadable timestamp" if began is None else f"starts {when(began)}"
        print(
            f"    warning: {part} has events before {when(plan.start)}"
            f" (the newest {newest}); they are NOT included and progress will not be"
            " set. Pass an earlier --start to include them."
        )
    if list_chunks:
        width = len(str(count))
        for index, chunk in enumerate(plan.chunks):
            print(f"    chunk {index + 1:>{width}}/{count}  {_span(chunk)}")


def _print_backfill_totals(results: tuple[BackfillResult, ...]) -> None:
    if not results:
        return
    print("Backfill totals:")
    width = max(len(r.stream) for r in results)
    for r in results:
        print(
            f"  {r.stream:<{width}}  chunks {r.chunks_done:>4,}  inserted {r.inserted:>8,}"
            f"  skipped {r.skipped:>8,}  held back {r.held_back:>3,}"
        )


def _failed(failure: StreamFailure, database: str, *, busy_hint: str | None = None) -> int:
    if failure.kind is FailureKind.SOURCE:
        return source_failed(failure.error)
    if failure.kind is FailureKind.ADAPTER:
        print(f"backfill stopped: {failure.error}", file=sys.stderr)
        return 1
    print(f"{database}: {failure.error}", file=sys.stderr)
    if busy_hint is not None and failure.kind is FailureKind.DATABASE_BUSY:
        print(busy_hint, file=sys.stderr)
    return 1


def _span(chunk: Chunk) -> str:
    return f"[{when(chunk.start)}, {when(chunk.end)})"
