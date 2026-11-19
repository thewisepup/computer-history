"""The status command: freshness, coverage gaps, the capture agent and row counts."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from computer_history.cli.db import outdated_note, store_unavailable
from computer_history.cli.formatting import ago, db_size, duration, lag, when
from computer_history.sources import (
    AX_TEXT_SOURCE,
    CAPTURE_TOLERANCE,
    UNREADABLE_FOLDER,
    ActivityWatch,
    AWClient,
    CaptureHealth,
    SourceUnavailable,
    capture_health,
    resolve_spool_path,
)
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
    spool_path = resolve_spool_path(args.spool_path, db_path)
    now = datetime.now(UTC)
    client = AWClient(args.aw_url, timeout=STATUS_AW_TIMEOUT_SECONDS)
    aw = ActivityWatch(client)
    try:
        streams = aw.streams()
        aw_error = None
    except SourceUnavailable as exc:
        streams, aw_error = [], str(exc)

    if aw_error is not None:
        print(f"!! ActivityWatch is UNREACHABLE at {args.aw_url}: nothing new can be ingested.")
        print(f"!! {aw_error}")
        print()
        aw_line = f"ActivityWatch: no  ({args.aw_url})"
    else:
        names = ", ".join(streams) or "none of window/AFK/web"
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
        health = capture_health(
            store.conn,
            summaries,
            spool_path,
            client if aw_error is None else None,
            now=now,
            window=STATUS_WINDOW,
            min_gap_seconds=MIN_GAP_SECONDS,
        )
        print()
        _print_sources(summaries, now)
        print()
        _print_gaps(store.conn, summaries, health)
        print()
        _print_agent(health, spool_path, now)
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
        print(
            f"  {s.source:<{width}}  {s.observation_count:>8,} observations"
            f"  latest end {when(s.latest_ended_at)}"
            f"  settled until {when(s.settled_until)} ({_freshness(s, now)})"
        )
    if any(s.source in ActivityWatch.projectors for s in summaries):
        print(
            "  (an ActivityWatch source is settled only up to the start of its current,"
            " still-growing window/tab/AFK event, so lag includes that event's length)"
        )


def _freshness(summary: SourceSummary, now: datetime) -> str:
    if summary.advanced_at is None:
        return "never ingested"
    if summary.settled_until is None:
        return f"progress moved {duration((now - summary.advanced_at).total_seconds())} ago"
    return lag(now - summary.settled_until)


def _print_gaps(
    conn: sqlite3.Connection, summaries: list[SourceSummary], health: CaptureHealth
) -> None:
    print(
        f"Coverage gaps (unobserved: nothing recorded) of {duration(MIN_GAP_SECONDS)} or"
        f" more, in the {STATUS_WINDOW.total_seconds() / 3600:g}h up to each source's"
        " settled-until time (or its latest observation, if it has none):"
    )
    if not summaries:
        print("  nothing to check yet")
    for s in summaries:
        if s.source == AX_TEXT_SOURCE and health.reported:
            _print_capture_gaps(health)
            continue
        end = s.settled_until or s.latest_ended_at
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


def _print_capture_gaps(health: CaptureHealth) -> None:
    coverage = health.coverage
    if coverage is None:
        print(f"  {AX_TEXT_SOURCE}: no settled span to check yet")
        return
    print(
        f"  {AX_TEXT_SOURCE} from {when(coverage.start)} to {when(coverage.end)} (unobserved:"
        f" aw-afk shows you active, no record within {duration(CAPTURE_TOLERANCE.total_seconds())},"
        " not paused):"
    )
    warnings = sorted(
        [(gap, "while you were active") for gap in coverage.unobserved]
        + [(gap, "cannot be judged: no aw-afk data") for gap in coverage.unjudged]
    )
    if not warnings:
        print(f"  {AX_TEXT_SOURCE}: no gaps since {when(coverage.start)}")
    for gap, why in warnings[:MAX_GAPS_SHOWN]:
        print(
            f"  warning: no {AX_TEXT_SOURCE} coverage from {when(gap.start)} to {when(gap.end)}"
            f" ({duration(gap.seconds)}), {why}"
        )
    if len(warnings) > MAX_GAPS_SHOWN:
        print(f"  warning: ... and {len(warnings) - MAX_GAPS_SHOWN} more {AX_TEXT_SOURCE} gaps")


def _print_agent(health: CaptureHealth, spool_path: Path, now: datetime) -> None:
    if not health.reported:
        print(f"Capture agent: has not reported yet (no {AX_TEXT_SOURCE} records stored)")
        print(f"  spool         {_spool(health, spool_path, now)}")
        return
    print("Capture agent:")
    print(f"  last capture  {ago(health.last_capture, now)}")
    print(f"  alive         {_alive(health, now)}")
    print(f"  spool         {_spool(health, spool_path, now)}")
    t = health.today
    print(
        f"  today         {t.captures:,} captures stored, {t.excluded:,} excluded,"
        f" {t.cut_off:,} cut off, {t.timed_out:,} timed out"
    )
    paused = "no" if health.paused_since is None else f"yes, since {ago(health.paused_since, now)}"
    print(f"  paused        {paused}")


def _alive(health: CaptureHealth, now: datetime) -> str:
    last = ago(health.last_record, now)
    if health.alive == "yes":
        return f"yes (last record {last})"
    if health.alive == "no":
        return f"NO: no record since {last}, although aw-afk shows you active since then"
    if health.alive == "paused":
        return f"paused, so no records are expected (last record {last})"
    return f"cannot tell: no record since {last}, and aw-afk does not show you active since then"


def _spool(health: CaptureHealth, spool_path: Path, now: datetime) -> str:
    spool = health.spool
    if spool is None:
        return f"cannot be inspected: {health.spool_error}"
    waiting = f"{spool.waiting:,} finished file{'' if spool.waiting == 1 else 's'} waiting"
    if spool.oldest_finished_at is not None:
        age = (now - spool.oldest_finished_at).total_seconds()
        oldest = duration(age) if age >= 0 else f"{duration(-age)} ahead of now"
        waiting += f" (oldest {oldest})"
    return f"{waiting}, {spool.unreadable:,} in {UNREADABLE_FOLDER}/  ({spool_path})"


def _print_counts(counts: dict[str, int]) -> None:
    print("Rows:")
    ordered = sorted(counts, key=lambda name: (name not in ("observations", "signals"), name))
    width = max((len(name) for name in ordered), default=0)
    for name in ordered:
        print(f"  {name:<{width}}  {counts[name]:>10,}")
