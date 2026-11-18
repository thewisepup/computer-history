"""The argument parser and command dispatch."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from computer_history.cli.backfill import cmd_backfill
from computer_history.cli.ingest import cmd_ingest
from computer_history.cli.rebuild import cmd_rebuild_signals
from computer_history.cli.status import cmd_status
from computer_history.sources import DEFAULT_AW_URL, POLL_INTERVAL_SECONDS

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

HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "ingest": cmd_ingest,
    "status": cmd_status,
    "rebuild-signals": cmd_rebuild_signals,
    "backfill": cmd_backfill,
}


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
    # Accepted before or after the subcommand.
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
