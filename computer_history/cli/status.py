"""The status command: freshness, coverage gaps and row counts."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime, timedelta

from computer_history.cli.db import outdated_note, store_unavailable
from computer_history.cli.formatting import db_size, duration, lag, when
from computer_history.sources import AWClient, AWError, discover_sources
from computer_history.store import (
    Purpose,
    SourceSummary,
    StoreState,
    find_gaps,
    open_store,
    resolve_db_path,
    source_summary,
    table_counts,
)

STATUS_WINDOW = timedelta(hours=24)
MIN_GAP_SECONDS = 300
MAX_GAPS_SHOWN = 10
STATUS_AW_TIMEOUT_SECONDS = 5


def cmd_status(args: argparse.Namespace) -> int:
    db_path = resolve_db_path(args.db_path)
    now = datetime.now(UTC)
    client = AWClient(args.aw_url, timeout=STATUS_AW_TIMEOUT_SECONDS)
    try:
        sources = discover_sources(client)
        aw_error = None
    except AWError as exc:
        sources, aw_error = [], str(exc)

    if aw_error is not None:
        print(f"!! ActivityWatch is UNREACHABLE at {args.aw_url}: nothing new can be ingested.")
        print(f"!! {aw_error}")
        print()
        aw_line = f"ActivityWatch: no  ({args.aw_url})"
    else:
        names = ", ".join(s.name for s in sources) or "none of window/AFK/web"
        aw_line = f"ActivityWatch: yes ({args.aw_url}; sources: {names})"

    store = open_store(db_path, Purpose.READ)
    if store.state is StoreState.MISSING:
        print(f"Database:      {db_path} (not created yet; run `computer-history ingest`)")
        print(aw_line)
        return 0
    if store.state in (StoreState.BUSY, StoreState.UNREADABLE):
        print(aw_line)
        return store_unavailable(store)
    print(f"Database:      {db_path} ({db_size(db_path)}, schema v{store.version})")
    print(aw_line)
    if store.state is StoreState.OUTDATED:
        print(f"  note: {outdated_note(store)}. No store details until then.")
        return 0
    if store.conn is None:
        return store_unavailable(store)
    with store:
        summaries = source_summary(store.conn)
        print()
        _print_sources(summaries, now)
        print()
        _print_gaps(store.conn, summaries)
        print()
        _print_counts(table_counts(store.conn))
    return 0


def _print_sources(summaries: list[SourceSummary], now: datetime) -> None:
    print("Sources:")
    if not summaries:
        print("  none yet (run `computer-history ingest`)")
        return
    width = max(len(s.source) for s in summaries)
    for s in summaries:
        freshness = "never ingested" if s.cursor is None else lag(now - s.cursor)
        print(
            f"  {s.source:<{width}}  {s.observation_count:>8,} observations"
            f"  latest end {when(s.latest_ended_at)}"
            f"  cursor {when(s.cursor)} ({freshness})"
        )
    print(
        "  (the cursor waits at the start of the current, still-growing window/tab/AFK"
        " event, so lag includes that event's length)"
    )


def _print_gaps(conn: sqlite3.Connection, summaries: list[SourceSummary]) -> None:
    print(
        f"Coverage gaps (unobserved: nothing recorded) of {duration(MIN_GAP_SECONDS)} or"
        f" more, in the {STATUS_WINDOW.total_seconds() / 3600:g}h up to each source's cursor"
        " (or its latest observation, if it has no cursor):"
    )
    if not summaries:
        print("  nothing to check yet")
    for s in summaries:
        end = s.cursor or s.latest_ended_at
        first = s.earliest_started_at
        if end is None or first is None:
            print(f"  {s.source}: no observations yet")
            continue
        start = max(end - STATUS_WINDOW, first)
        if start >= end:
            print(f"  {s.source}: no settled span to check yet")
            continue
        gaps = find_gaps(conn, s.source, start, end, min_gap_seconds=MIN_GAP_SECONDS)
        if not gaps:
            print(f"  {s.source}: no gaps since {when(start)}")
        for gap in gaps[:MAX_GAPS_SHOWN]:
            print(
                f"  warning: no {s.source} coverage from {when(gap.start)} to"
                f" {when(gap.end)} ({duration(gap.seconds)})"
            )
        if len(gaps) > MAX_GAPS_SHOWN:
            print(f"  warning: ... and {len(gaps) - MAX_GAPS_SHOWN} more {s.source} gaps")


def _print_counts(counts: dict[str, int]) -> None:
    print("Rows:")
    ordered = sorted(counts, key=lambda name: (name not in ("observations", "signals"), name))
    width = max((len(name) for name in ordered), default=0)
    for name in ordered:
        print(f"  {name:<{width}}  {counts[name]:>10,}")
