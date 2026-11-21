from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import computer_history
from computer_history.cli.backfill import cmd_backfill
from computer_history.cli.dev import add_dev_commands, cmd_dev
from computer_history.cli.ingest import cmd_ingest
from computer_history.cli.profile import profile_line
from computer_history.cli.rebuild import cmd_rebuild_signals
from computer_history.cli.status import cmd_status
from computer_history.sources import DEFAULT_AW_URL, POLL_INTERVAL_SECONDS
from computer_history.store import LiveDatabaseRefused, resolve_db_path, running_code

CODE_LOCATION = Path(computer_history.__file__).resolve().parent
DATABASE_COMMANDS = frozenset({"ingest", "status", "rebuild-signals", "backfill"})

COMMANDS = {
    "ingest": "Ingest settled ActivityWatch events and the capture spool into the store.",
    "status": "Show store and source status.",
    "rebuild-signals": (
        "Rebuild derived signals from stored observations (blocks ingest while running)."
    ),
    "backfill": (
        "One-time ingest of existing ActivityWatch history, in bounded chunks"
        " (idempotent: re-running adds nothing)."
    ),
    "dev": (
        "Developer tools: build-db makes a database of synthetic history, perf runs the"
        " performance gate, bench times each operation."
    ),
}

HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "ingest": cmd_ingest,
    "status": cmd_status,
    "rebuild-signals": cmd_rebuild_signals,
    "backfill": cmd_backfill,
    "dev": cmd_dev,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="computer-history",
        description="Local activity store and ActivityWatch ingest.",
    )
    db_help = (
        "SQLite database path (default: $COMPUTER_HISTORY_DB, else history.db in the profile's"
        " data folder: ~/Library/Application Support/ComputerHistory-dev/ for dev,"
        " ComputerHistory/ for stable)"
    )
    parser.add_argument("--db-path", help=db_help)
    db_after_command = argparse.ArgumentParser(add_help=False)
    db_after_command.add_argument("--db-path", default=argparse.SUPPRESS, help=db_help)
    aw = argparse.ArgumentParser(add_help=False)
    aw.add_argument(
        "--aw-url",
        default=DEFAULT_AW_URL,
        help=f"ActivityWatch API base URL (default: {DEFAULT_AW_URL})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in COMMANDS.items():
        if name == "dev":
            add_dev_commands(subparsers.add_parser(name, help=help_text, description=help_text))
            continue
        if name in ("ingest", "status", "backfill"):
            parents = [db_after_command, aw]
        else:
            parents = [db_after_command]
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
                type=when_arg,
                help="backfill from this ISO date/datetime (local time unless it has an"
                " offset) instead of where the ActivityWatch buckets begin",
            )
            sub.add_argument(
                "--end",
                type=when_arg,
                help="stop at this ISO date/datetime (default: the time the source's ingest"
                " is settled until, or now; never later than those)",
            )
            sub.add_argument(
                "--dry-run",
                action="store_true",
                help="discover sources and print the planned chunks; write nothing",
            )
        if name in ("ingest", "status"):
            sub.add_argument(
                "--spool-path",
                help="capture spool folder (default: $COMPUTER_HISTORY_SPOOL, else spool/ beside"
                " the database)",
            )
        if name == "ingest":
            sub.add_argument(
                "--watch",
                action="store_true",
                help=f"poll every {POLL_INTERVAL_SECONDS}s until interrupted (Ctrl-C)",
            )
    return parser


def when_arg(value: str) -> datetime:
    """An ISO date or datetime. Local time unless it carries an offset."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"not an ISO date or datetime: {value!r} (e.g. 2026-11-01 or 2026-11-01T09:00)"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(UTC)


def main(argv: Sequence[str] | None = None, *, code: Path = CODE_LOCATION) -> int:
    """Run one command; the profile is decided from where the code runs."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    running = running_code(code)
    args.profile = running.profile
    handler = HANDLERS.get(args.command)
    if handler is None:
        print(f"computer-history {args.command}: not implemented yet", file=sys.stderr)
        return 1
    uses = None
    if args.command in DATABASE_COMMANDS:
        try:
            args.database = resolve_db_path(args.db_path, args.profile)
        except LiveDatabaseRefused as exc:
            print(profile_line(running, code, "database refused"), flush=True)
            return _refused(exc)
        uses = f"database {args.database}"
    elif args.command == "dev" and args.dev_command == "build-db":
        uses = f"output {args.out}"
    print(profile_line(running, code, uses), flush=True)
    try:
        return handler(args)
    except LiveDatabaseRefused as exc:
        return _refused(exc)


def _refused(exc: LiveDatabaseRefused) -> int:
    print(f"refused: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
