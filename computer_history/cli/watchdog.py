from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from socket import gethostname

from computer_history.cli import formatting
from computer_history.cli.formatting import duration, finding_lines
from computer_history.cli.sources import AW_CHECK_TIMEOUT_SECONDS
from computer_history.sources import (
    AWClient,
    agent_config_path,
    health_path,
    resolve_spool_path,
)
from computer_history.store import Purpose, StoreState, open_store
from computer_history.watchdog import (
    REOPEN_LIMIT,
    WatchdogRun,
    WatchPaths,
    watch_once,
    watchdog_lock_path,
    watchdog_state_path,
)


def cmd_watchdog(args: argparse.Namespace) -> int:
    db_path: Path = args.database
    paths = WatchPaths(
        spool=resolve_spool_path(args.spool_path, db_path, args.profile),
        health=health_path(db_path),
        config=agent_config_path(db_path),
        state=watchdog_state_path(db_path),
        lock=watchdog_lock_path(db_path),
    )
    now = formatting.utc_now()
    client = AWClient(args.aw_url, timeout=AW_CHECK_TIMEOUT_SECONDS)
    with open_store(db_path, Purpose.READ) as store:
        if store.state not in (StoreState.READY, StoreState.MISSING):
            print(f"note: the database is {store.state.value}; judging from the spool alone")
        conn = store.conn if store.state is StoreState.READY else None
        report = watch_once(args.host, conn, client, paths, now=now, hostname=gethostname())
    if report is not None:
        _print_run(report, now)
    return 0


def _print_run(report: WatchdogRun, now: datetime) -> None:
    for message in report.to_log:
        print(message, file=sys.stderr)
    limits = ", ".join(
        f"{check.value} {duration(after.total_seconds())}"
        for check, after in report.thresholds.silent_after.items()
    )
    print(f"Watchdog (silent after: {limits})")
    for line in finding_lines(report.state.findings, now):
        print(line)
    for notice in report.posted:
        print(f"  {'cleared' if notice.cleared else 'notified'}: {notice.message}")
    reopening = report.reopening
    if reopening is not None and reopening.reopened:
        print("  reopened ActivityWatch")
    if reopening is not None and reopening.refused:
        print(f"  did not reopen ActivityWatch: reopened {REOPEN_LIMIT} times in the last hour")
    for problem in report.thresholds.problems:
        print(f"  config problem: {problem}")
    for error in report.state.errors:
        print(f"  error: {error}")
