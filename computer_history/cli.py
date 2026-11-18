"""Command-line entry point for the ``computer-history`` console script."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

COMMANDS = {
    "ingest": "Ingest settled ActivityWatch events into the store.",
    "status": "Show store and source status.",
    "rebuild-signals": "Rebuild derived signals from stored observations.",
    "backfill": "Ingest ActivityWatch history for a past time range.",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="computer-history",
        description="Local activity store and ActivityWatch ingest.",
    )
    parser.add_argument(
        "--db-path",
        help=(
            "SQLite database path (default: $COMPUTER_HISTORY_DB, else "
            "~/Library/Application Support/ComputerHistory/history.db)"
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in COMMANDS.items():
        subparsers.add_parser(name, help=help_text, description=help_text)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"computer-history {args.command}: not implemented yet", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
