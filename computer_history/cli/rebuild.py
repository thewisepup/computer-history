"""The rebuild-signals command."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Sequence

from computer_history.cli.db import db_busy_hint, open_store
from computer_history.sources import project_signal
from computer_history.store import RebuildAborted, rebuild_signals, resolve_db_path


def cmd_rebuild_signals(args: argparse.Namespace) -> int:
    db_path = resolve_db_path(args.db_path)
    if not db_path.exists():
        print(f"no database at {db_path}; run `computer-history ingest` first", file=sys.stderr)
        return 1
    conn = open_store(db_path)
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
        print(db_busy_hint(db_path), file=sys.stderr)
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
    """Format ids like "3, 7, 9", plus "(and N more)" when they are a sample."""
    text = ", ".join(str(i) for i in ids) or "-"
    if total > len(ids):
        text += f" (and {total - len(ids):,} more)"
    return text
