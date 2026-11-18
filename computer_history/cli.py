"""Command-line entry point for the computer-history console script.

Thin by design: argument plumbing and formatting only. The real work lives in
the sources and store packages.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from computer_history.sources import (
    BACKFILL_CHUNK,
    DEFAULT_AW_URL,
    AWApi,
    AWClient,
    AWError,
    BackfillPlan,
    BackfillResult,
    Chunk,
    IngestOutcome,
    discover_sources,
    ingest_source,
    plan_backfill,
    project_signal,
    run_backfill,
)
from computer_history.store import (
    RebuildAborted,
    SourceSummary,
    connect,
    connect_readonly,
    find_gaps,
    get_cursor,
    load_migrations,
    rebuild_signals,
    resolve_db_path,
    schema_version,
    source_summary,
    table_counts,
)

log = logging.getLogger(__name__)

COMMANDS = {
    "ingest": "Ingest settled ActivityWatch events into the store.",
    "status": "Show store and source status.",
    "rebuild-signals": (
        "Rebuild derived signals from stored observations (blocks ingest while running)."
    ),
    "backfill": (
        "One-time ingest of existing ActivityWatch history, in bounded chunks"
        " (idempotent: re-running adds nothing)."
    ),
}

POLL_INTERVAL_SECONDS = 60
# status: look for coverage gaps this far back from each source's cursor...
STATUS_WINDOW = timedelta(hours=24)
# ...and report only gaps at least this long.
MIN_GAP_SECONDS = 300
MAX_GAPS_SHOWN = 10
# status only probes reachability; don't hang on a wedged server.
STATUS_AW_TIMEOUT_SECONDS = 5


# --- ingest ------------------------------------------------------------------


@dataclass(frozen=True)
class CycleSummary:
    """What one poll cycle did: the outcomes of the sources that committed and,
    if the cycle stopped early, why and on which source."""

    at: datetime
    outcomes: dict[str, IngestOutcome] = field(default_factory=dict)
    error: str | None = None
    failed_source: str | None = None  # None with an error: failed before any source
    database_error: bool = False  # the store failed, not ActivityWatch

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
    """One incremental poll of every source; never raises for a transient failure.

    An unreachable ActivityWatch or a locked database ends the cycle and is
    returned in the summary, together with the outcomes of the sources that
    committed before it. Those stay committed; the next cycle resumes from the
    cursors. Other database errors are not transient and propagate.
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

    Cycles start every interval seconds; a transient failure is logged and
    retried next cycle.
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
    conn = _open_store(db_path)
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
        print(_db_busy_hint(db_path), file=sys.stderr)
    else:
        print("Is ActivityWatch running? Check with `computer-history status`.", file=sys.stderr)
    return 1


# --- status ------------------------------------------------------------------


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

    if not db_path.exists():
        print(f"Database:      {db_path} (not created yet; run `computer-history ingest`)")
        print(aw_line)
        return 0
    # Read-only: status never creates, migrates or writes the store.
    conn = connect_readonly(db_path)
    try:
        version, expected = schema_version(conn), load_migrations()[-1].version
        print(f"Database:      {db_path} ({_db_size(db_path)}, schema v{version})")
        print(aw_line)
        if version < expected:
            print(
                f"  note: this CLI uses schema v{expected}; `computer-history ingest` will"
                " migrate the database. No store details until then."
            )
            return 0
        if version > expected:
            print(
                f"  note: schema v{version} is newer than this CLI understands"
                f" (v{expected}); upgrade computer-history."
            )
            return 0
        summaries = source_summary(conn)
        print()
        _print_sources(summaries, now)
        print()
        _print_gaps(conn, summaries)
        print()
        _print_counts(table_counts(conn))
    finally:
        conn.close()
    return 0


def _print_sources(summaries: list[SourceSummary], now: datetime) -> None:
    print("Sources:")
    if not summaries:
        print("  none yet (run `computer-history ingest`)")
        return
    width = max(len(s.source) for s in summaries)
    for s in summaries:
        lag = "never ingested" if s.cursor is None else _lag(now - s.cursor)
        print(
            f"  {s.source:<{width}}  {s.observation_count:>8,} observations"
            f"  latest end {_when(s.latest_ended_at)}"
            f"  cursor {_when(s.cursor)} ({lag})"
        )
    print(
        "  (the cursor waits at the start of the current, still-growing window/tab/AFK"
        " event, so lag includes that event's length)"
    )


def _print_gaps(conn: sqlite3.Connection, summaries: list[SourceSummary]) -> None:
    print(
        f"Coverage gaps (unobserved: nothing recorded) of {_duration(MIN_GAP_SECONDS)} or"
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
        # Ending at the cursor, not now: the last ~2 minutes are never settled yet.
        # Starting no earlier than the first event: time before recording began
        # is not a gap.
        start = max(end - STATUS_WINDOW, first)
        if start >= end:
            print(f"  {s.source}: no settled span to check yet")
            continue
        gaps = find_gaps(conn, s.source, start, end, min_gap_seconds=MIN_GAP_SECONDS)
        if not gaps:
            print(f"  {s.source}: no gaps since {_when(start)}")
        for gap in gaps[:MAX_GAPS_SHOWN]:
            print(
                f"  warning: no {s.source} coverage from {_when(gap.start)} to"
                f" {_when(gap.end)} ({_duration(gap.seconds)})"
            )
        if len(gaps) > MAX_GAPS_SHOWN:
            print(f"  warning: ... and {len(gaps) - MAX_GAPS_SHOWN} more {s.source} gaps")


def _print_counts(counts: dict[str, int]) -> None:
    print("Rows:")
    # observations and signals first; the rest (empty until later milestones) after.
    ordered = sorted(counts, key=lambda name: (name not in ("observations", "signals"), name))
    width = max((len(name) for name in ordered), default=0)
    for name in ordered:
        print(f"  {name:<{width}}  {counts[name]:>10,}")


# --- rebuild-signals -------------------------------------------------------------


def cmd_rebuild_signals(args: argparse.Namespace) -> int:
    db_path = resolve_db_path(args.db_path)
    if not db_path.exists():
        print(f"no database at {db_path}; run `computer-history ingest` first", file=sys.stderr)
        return 1
    conn = _open_store(db_path)
    if conn is None:
        return 1
    try:
        result = rebuild_signals(conn, project_signal, allow_shrink=args.allow_shrink)
    except RebuildAborted as exc:
        print(f"rebuild-signals aborted: {exc}", file=sys.stderr)
        if exc.failed:
            print(
                f"  first failing observation ids: {_ids(exc.failed_ids, exc.failed)}",
                file=sys.stderr,
            )
        if exc.shrink:
            print(
                "  if the mapping change is meant to drop them, re-run with --allow-shrink",
                file=sys.stderr,
            )
        return 1
    except sqlite3.OperationalError as exc:
        print(f"rebuild-signals failed, signals unchanged: {exc}", file=sys.stderr)
        print(_db_busy_hint(db_path), file=sys.stderr)
        return 1
    finally:
        conn.close()
    print(f"Rebuilt signals in {db_path} from stored observations")
    print(f"  signals before   {result.signals_before:>10,}")
    print(f"  signals after    {result.signals_after:>10,}")
    print(f"  skipped          {result.skipped:>10,}  (malformed payloads)")
    if result.skipped:
        print(
            f"  warning: {result.skipped:,} observations could not be projected and now have"
            f" no signal; first ids: {_ids(result.failed_ids, result.skipped)}"
        )
    return 0


def _ids(ids: Sequence[int], total: int) -> str:
    """Like "3, 7, 9", plus "(and N more)" when the ids are a sample."""
    text = ", ".join(str(i) for i in ids) or "-"
    if total > len(ids):
        text += f" (and {total - len(ids):,} more)"
    return text


# --- backfill --------------------------------------------------------------------


def cmd_backfill(args: argparse.Namespace) -> int:
    """Plan every source, then (unless --dry-run) ingest each plan chunk by chunk.

    All planning (AW discovery and probes, cursors read read-only) happens before
    the store is opened, so an unreachable AW creates nothing. A missing database
    is then created: backfill may be the first command ever run.
    """
    db_path = resolve_db_path(args.db_path)
    client = AWClient(args.aw_url)
    now = datetime.now(UTC)
    if args.start is not None and args.end is not None and args.start >= args.end:
        print("--start must be before --end", file=sys.stderr)
        return 2
    try:
        buckets = client.get_buckets()  # one listing for discovery and every plan
        sources = discover_sources(client, buckets=buckets)
        if not sources:
            print("no ActivityWatch sources found (no window, AFK or web buckets)")
            return 0
        # Read-only. A cursor that an ingest writes after this read is still safe:
        # the plan merely ends at now instead, and init_cursor never overwrites it.
        cursors = _read_cursors(db_path, [s.name for s in sources])
        if cursors is None:
            return 1
        plans = [
            plan_backfill(
                client,
                source,
                cursor=cursors.get(source.name),
                now=now,
                start=args.start,
                end=args.end,
                buckets=buckets,
            )
            for source in sources
        ]
    except AWError as exc:
        return _aw_failed(exc)

    verb = "Dry run: would backfill" if args.dry_run else "Backfilling"
    width = _duration(BACKFILL_CHUNK.total_seconds())
    print(f"{verb} {args.aw_url} into {db_path} ({width} chunks)", flush=True)
    for plan in plans:
        _print_plan(plan, list_chunks=args.dry_run)
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    conn = _open_store(db_path)
    if conn is None:
        return 1
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
            print(_db_busy_hint(db_path), file=sys.stderr)
        code = 1
    except KeyboardInterrupt:
        _print_backfill_totals(results)
        print("backfill interrupted", file=sys.stderr)
        code = 130
    else:
        print()
        _print_backfill_totals(results)
        return 0
    finally:
        conn.close()
    if results:  # at least one chunk committed
        print(_RESUME_HINT, file=sys.stderr)
    return code


_RESUME_HINT = (
    "Committed chunks are kept; re-run `computer-history backfill` to finish"
    " (done chunks only produce duplicates)."
)


def _backfill_one(
    conn: sqlite3.Connection, client: AWApi, plan: BackfillPlan, results: list[BackfillResult]
) -> None:
    """Run one plan, printing a line per chunk and a closing summary for the source.

    The running totals join results after the first committed chunk, so the
    caller can still print them if a later chunk fails.
    """
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
            line += f"  incomplete from {_when(outcome.frontier)}"
        print(line, flush=True)
        last = tick

    result = run_backfill(conn, client, plan, on_chunk=progress)
    print(
        f"  {plan.source.name} done in {_duration(time.monotonic() - began)}:"
        f" inserted {result.inserted:,}, skipped {result.skipped:,},"
        f" held back {result.held_back:,}",
        flush=True,
    )
    # With no cursor before the run, ingest reads from the backfill's frontier (or
    # from the beginning): it covers every incomplete chunk. With one, the holes
    # before it are backfill's to fill.
    later = (
        "`computer-history ingest` picks them up once settled"
        if plan.cursor is None
        else "re-run backfill later to fill them"
    )
    for chunk, frontier in result.incomplete:
        print(
            f"  note: {plan.source.name} events from {_when(frontier)} to {_when(chunk.end)}"
            f" had not settled yet (held back); {later}"
        )
    if result.cursor_set:
        print(
            f"  cursor set to {_when(result.complete_until)}: `computer-history ingest`"
            " continues from there without re-reading history"
        )
    elif plan.cursor is not None:
        print(f"  cursor unchanged at {_when(plan.cursor)} (incremental ingest owns what follows)")
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
        bound = f"up to its cursor {_when(plan.cursor)}"
    else:
        bound = "up to now (no cursor yet)"
    if plan.start is None:
        print(
            f"{head} cannot tell where its history begins (no bucket has a usable"
            " 'created' time); pass --start"
        )
        return
    if not plan.chunks:
        print(f"{head} nothing to backfill: {_when(plan.start)} is not before {_when(plan.end)}")
        return
    count = len(plan.chunks)
    print(
        f"{head} {_span(Chunk(plan.start, plan.end))} {bound},"
        f" {count} chunk{'s' if count != 1 else ''}",
        flush=True,
    )
    for bucket_id, began in plan.earlier:
        newest = "has an unreadable timestamp" if began is None else f"starts {_when(began)}"
        print(
            f"    warning: {bucket_id} has events before {_when(plan.start)}"
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


def _read_cursors(db_path: Path, sources: Sequence[str]) -> dict[str, str | None] | None:
    """Cursors from an existing store, read-only.

    Empty when there is no database (or an unmigrated one); None after
    printing why it could not be read.
    """
    if not db_path.exists():
        return {}
    try:
        conn = connect_readonly(db_path)
        try:
            if schema_version(conn) < 1:
                return {}
            return {name: get_cursor(conn, name) for name in sources}
        finally:
            conn.close()
    except sqlite3.Error as exc:
        print(f"cannot read {db_path}: {exc}", file=sys.stderr)
        return None


def _aw_failed(exc: AWError) -> int:
    print(f"error: {exc}", file=sys.stderr)
    print("Is ActivityWatch running? Check with `computer-history status`.", file=sys.stderr)
    return 1


def _span(chunk: Chunk) -> str:
    return f"[{_when(chunk.start)}, {_when(chunk.end)})"


def _when_arg(value: str) -> datetime:
    """An ISO date or datetime; local time unless it carries an offset."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"not an ISO date or datetime: {value!r} (e.g. 2026-11-01 or 2026-11-01T09:00)"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()  # naive -> the local zone
    return parsed.astimezone(UTC)


# --- shared ----------------------------------------------------------------------


def _open_store(db_path: Path) -> sqlite3.Connection | None:
    """Open (and migrate if needed) the store, or None after printing why it failed.

    A lock held by another writer surfaces here once the busy timeout runs out.
    """
    try:
        return connect(db_path)
    except sqlite3.OperationalError as exc:
        print(f"cannot open {db_path}: {exc}", file=sys.stderr)
        print(_db_busy_hint(db_path), file=sys.stderr)
        return None


def _db_busy_hint(db_path: Path) -> str:
    return f"Is another process writing to {db_path}? Try again shortly."


# --- formatting ----------------------------------------------------------------


def _duration(seconds: float) -> str:
    """Like 42s, 3m 12s, 2h 5m, 1d 3h: the two largest non-zero units."""
    total = max(0, round(seconds))
    if total < 60:
        return f"{total}s"
    parts = []
    for suffix, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        value, total = divmod(total, size)
        if value:
            parts.append(f"{value}{suffix}")
            if len(parts) == 2:
                break
    return " ".join(parts)


def _lag(delta: timedelta) -> str:
    seconds = delta.total_seconds()
    if seconds < 0:
        return f"{_duration(-seconds)} ahead of now"
    return f"{_duration(seconds)} behind now"


def _when(value: datetime | None) -> str:
    """Local wall-clock time, minute precision; a dash for missing."""
    return "-" if value is None else value.astimezone().strftime("%Y-%m-%d %H:%M")


def _db_size(path: Path) -> str:
    size = _bytes(path.stat().st_size)
    wal = path.with_name(path.name + "-wal")
    if wal.exists() and wal.stat().st_size:
        size += f" + {_bytes(wal.stat().st_size)} WAL"
    return size


def _bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    value = n / 1024
    for unit in ("KB", "MB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


# --- entry point ---------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="computer-history",
        description="Local activity store and ActivityWatch ingest.",
    )
    db_help = (
        "SQLite database path (default: $COMPUTER_HISTORY_DB, else "
        "~/Library/Application Support/ComputerHistory/history.db)"
    )
    parser.add_argument("--db-path", help=db_help)
    # Also accepted after the subcommand; SUPPRESS keeps a value given before it.
    db = argparse.ArgumentParser(add_help=False)
    db.add_argument("--db-path", default=argparse.SUPPRESS, help=db_help)
    aw = argparse.ArgumentParser(add_help=False)
    aw.add_argument(
        "--aw-url",
        default=DEFAULT_AW_URL,
        help=f"ActivityWatch API base URL (default: {DEFAULT_AW_URL})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in COMMANDS.items():
        parents = [db, aw] if name in ("ingest", "status", "backfill") else [db]
        sub = subparsers.add_parser(name, help=help_text, description=help_text, parents=parents)
        if name == "rebuild-signals":
            sub.add_argument(
                "--allow-shrink",
                action="store_true",
                help="allow a rebuild that drops more than half of the existing signals"
                " (refused by default as a likely mapping bug)",
            )
        if name == "backfill":
            sub.add_argument(
                "--start",
                type=_when_arg,
                help="backfill from this ISO date/datetime (local time unless it has an"
                " offset) instead of where the ActivityWatch buckets begin",
            )
            sub.add_argument(
                "--end",
                type=_when_arg,
                help="stop at this ISO date/datetime (default: the source's ingest cursor,"
                " or now; never later than those)",
            )
            sub.add_argument(
                "--dry-run",
                action="store_true",
                help="discover sources and print the planned chunks; write nothing",
            )
        if name == "ingest":
            sub.add_argument(
                "--watch",
                action="store_true",
                help=f"poll every {POLL_INTERVAL_SECONDS}s until interrupted (Ctrl-C)",
            )
    return parser


HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "ingest": cmd_ingest,
    "status": cmd_status,
    "rebuild-signals": cmd_rebuild_signals,
    "backfill": cmd_backfill,
}


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = HANDLERS.get(args.command)
    if handler is None:
        print(f"computer-history {args.command}: not implemented yet", file=sys.stderr)
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
