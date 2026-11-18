"""The backfill command: plan, then ingest history chunk by chunk."""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from computer_history.cli.db import db_busy_hint, store_unavailable
from computer_history.cli.formatting import duration, when
from computer_history.sources import (
    BACKFILL_CHUNK,
    AWApi,
    AWClient,
    AWError,
    BackfillPlan,
    BackfillResult,
    Chunk,
    IngestOutcome,
    plan_all_backfills,
    run_backfill,
)
from computer_history.store import (
    Purpose,
    StoreState,
    open_store,
    resolve_db_path,
)


def cmd_backfill(args: argparse.Namespace) -> int:
    """Plan every source, then ingest each plan chunk by chunk.

    A missing database is created only once planning succeeds, and a dry run never writes.
    """
    db_path = resolve_db_path(args.db_path)
    client = AWClient(args.aw_url)
    now = datetime.now(UTC)
    if args.start is not None and args.end is not None and args.start >= args.end:
        print("--start must be before --end", file=sys.stderr)
        return 2
    store = open_store(db_path, Purpose.READ if args.dry_run else Purpose.WRITE_EXISTING)
    if store.conn is None and store.state is not StoreState.MISSING:
        return store_unavailable(store)
    with store:
        try:
            plans = plan_all_backfills(store.conn, client, now=now, start=args.start, end=args.end)
        except AWError as exc:
            return _aw_failed(exc)
        except sqlite3.Error as exc:
            print(f"cannot read {db_path}: {exc}", file=sys.stderr)
            return 1
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
            return _backfill_all(store.conn, client, plans, db_path)
    with open_store(db_path, Purpose.WRITE) as created:
        if created.conn is None:
            return store_unavailable(created)
        return _backfill_all(created.conn, client, plans, db_path)


def _backfill_all(
    conn: sqlite3.Connection, client: AWApi, plans: list[BackfillPlan], db_path: Path
) -> int:
    """Run every plan, then print the totals and, after a failure, how to resume."""
    results: list[BackfillResult] = []
    try:
        for plan in plans:
            if not plan.chunks:
                continue
            print(flush=True)
            _backfill_one(conn, client, plan, results)
    except AWError as exc:
        _print_backfill_totals(results)
        code = _aw_failed(exc)
    except sqlite3.Error as exc:
        _print_backfill_totals(results)
        print(f"backfill stopped: database error: {exc}", file=sys.stderr)
        if isinstance(exc, sqlite3.OperationalError):
            print(db_busy_hint(db_path), file=sys.stderr)
        code = 1
    except KeyboardInterrupt:
        _print_backfill_totals(results)
        print("backfill interrupted", file=sys.stderr)
        code = 130
    else:
        print()
        _print_backfill_totals(results)
        return 0
    if results:
        print(_RESUME_HINT, file=sys.stderr)
    return code


_RESUME_HINT = (
    "Committed chunks are kept; re-run `computer-history backfill` to finish"
    " (done chunks only produce duplicates)."
)


def _backfill_one(
    conn: sqlite3.Connection, client: AWApi, plan: BackfillPlan, results: list[BackfillResult]
) -> None:
    """Run one plan, printing a line per chunk and a closing summary for the source."""
    total = len(plan.chunks)
    width = len(str(total))
    began = time.monotonic()
    last = began

    def progress(index: int, chunk: Chunk, outcome: IngestOutcome, so_far: BackfillResult) -> None:
        nonlocal last
        if index == 0:
            results.append(so_far)
        tick = time.monotonic()
        line = (
            f"  {plan.source.name} chunk {index + 1:>{width}}/{total}  {_span(chunk)}"
            f"  inserted {outcome.inserted:>6,}  skipped {outcome.skipped:>6,}"
            f"  held back {outcome.held_back:>3,}  ({tick - last:.1f}s)"
        )
        if outcome.frontier is not None and outcome.frontier < chunk.end:
            line += f"  incomplete from {when(outcome.frontier)}"
        print(line, flush=True)
        last = tick

    result = run_backfill(conn, client, plan, on_chunk=progress)
    print(
        f"  {plan.source.name} done in {duration(time.monotonic() - began)}:"
        f" inserted {result.inserted:,}, skipped {result.skipped:,},"
        f" held back {result.held_back:,}",
        flush=True,
    )
    later = (
        "`computer-history ingest` picks them up once settled"
        if plan.cursor is None
        else "re-run backfill later to fill them"
    )
    for chunk, frontier in result.incomplete:
        print(
            f"  note: {plan.source.name} events from {when(frontier)} to {when(chunk.end)}"
            f" had not settled yet (held back); {later}"
        )
    if result.cursor_set:
        print(
            f"  cursor set to {when(result.complete_until)}: `computer-history ingest`"
            " continues from there without re-reading history"
        )
    elif plan.cursor is not None:
        print(f"  cursor unchanged at {when(plan.cursor)} (incremental ingest owns what follows)")
    elif not plan.covers_history:
        print(
            "  cursor not set: this range does not start before all of the source's"
            " history, so the next `ingest` reads from the beginning"
        )
    else:
        print("  cursor not set: another ingest set it meanwhile")


def _print_plan(plan: BackfillPlan, *, list_chunks: bool) -> None:
    name = plan.source.name
    buckets = len(plan.source.bucket_ids)
    head = f"  {name} ({buckets} bucket{'s' if buckets != 1 else ''}):"
    if plan.cursor is not None:
        bound = f"up to its cursor {when(plan.cursor)}"
    else:
        bound = "up to now (no cursor yet)"
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
    for bucket_id, began in plan.earlier:
        newest = "has an unreadable timestamp" if began is None else f"starts {when(began)}"
        print(
            f"    warning: {bucket_id} has events before {when(plan.start)}"
            f" (the newest {newest}); they are NOT included and the cursor will not be"
            " set. Pass an earlier --start to include them."
        )
    if list_chunks:
        width = len(str(count))
        for index, chunk in enumerate(plan.chunks):
            print(f"    chunk {index + 1:>{width}}/{count}  {_span(chunk)}")


def _print_backfill_totals(results: list[BackfillResult]) -> None:
    if not results:
        return
    print("Backfill totals:")
    width = max(len(r.source) for r in results)
    for r in results:
        print(
            f"  {r.source:<{width}}  chunks {r.chunks_done:>4,}  inserted {r.inserted:>8,}"
            f"  skipped {r.skipped:>8,}  held back {r.held_back:>3,}"
        )


def _aw_failed(exc: AWError) -> int:
    print(f"error: {exc}", file=sys.stderr)
    print("Is ActivityWatch running? Check with `computer-history status`.", file=sys.stderr)
    return 1


def _span(chunk: Chunk) -> str:
    return f"[{when(chunk.start)}, {when(chunk.end)})"
