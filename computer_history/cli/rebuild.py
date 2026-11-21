from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
import time
from collections.abc import Sequence

from computer_history.cli.db import db_busy_hint, store_unavailable
from computer_history.sources import reproject_signals
from computer_history.store import (
    Purpose,
    RebuildAborted,
    RebuildResult,
    open_store,
    resolve_db_path,
)

log = logging.getLogger(__name__)


def cmd_rebuild_signals(args: argparse.Namespace) -> int:
    db_path = resolve_db_path(args.db_path)
    store = open_store(db_path, Purpose.WRITE_EXISTING)
    conn = store.conn
    if conn is None:
        return store_unavailable(store)
    with store:
        log.info("rebuild started", extra={"allow_shrink": args.allow_shrink})
        began = time.monotonic()
        outcome = "crashed"
        result: RebuildResult | None = None
        try:
            result = reproject_signals(conn, allow_shrink=args.allow_shrink)
            outcome = "ok"
        except RebuildAborted as exc:
            outcome = "aborted"
            log.error(
                "rebuild aborted",
                extra={"reason": str(exc), "failed": exc.failed, "shrink": exc.shrink},
            )
            print(f"rebuild-signals aborted: {exc}", file=sys.stderr)
            if exc.failed:
                print(
                    f"  first failing observation ids: {_id_sample(exc.failed_ids, exc.failed)}",
                    file=sys.stderr,
                )
            if exc.shrink:
                print(
                    "  if the mapping change is meant to drop them, re-run with --allow-shrink",
                    file=sys.stderr,
                )
            if exc.unclaimed:
                print(
                    "  this computer-history has no adapter for that source;"
                    " rebuild with the version that ingested it",
                    file=sys.stderr,
                )
            return 1
        except sqlite3.OperationalError as exc:
            outcome = "failed"
            log.exception("rebuild failed")
            print(f"rebuild-signals failed, signals unchanged: {exc}", file=sys.stderr)
            print(db_busy_hint(db_path), file=sys.stderr)
            return 1
        finally:
            log.info(
                "rebuild finished",
                extra={
                    "outcome": outcome,
                    "duration_ms": round((time.monotonic() - began) * 1000),
                    **({} if result is None else result._asdict()),
                },
            )
    assert result is not None
    print(f"Rebuilt signals in {db_path} from stored observations")
    print(f"  signals before   {result.signals_before:>10,}")
    print(f"  signals after    {result.signals_after:>10,}")
    print(f"  skipped          {result.skipped:>10,}  (malformed payloads)")
    if result.skipped:
        print(
            f"  warning: {result.skipped:,} observations could not be projected and now have"
            f" no signal; first ids: {_id_sample(result.failed_ids, result.skipped)}"
        )
    return 0


def _id_sample(ids: Sequence[int], total: int) -> str:
    text = ", ".join(str(i) for i in ids) or "-"
    if total > len(ids):
        text += f" (and {total - len(ids):,} more)"
    return text
