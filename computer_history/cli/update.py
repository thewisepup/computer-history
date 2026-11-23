from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path

from computer_history.cli import formatting
from computer_history.cli.formatting import release_gate_lines
from computer_history.cli.sources import AW_CHECK_TIMEOUT_SECONDS
from computer_history.sources import (
    AWClient,
    active_time,
    health_path,
    newest_record,
    read_health,
)
from computer_history.sources.activitywatch import AWApi
from computer_history.sources.capture_spool import default_spool_path
from computer_history.stable import (
    NOTHING_CHANGED,
    AgentCheck,
    AgentOutcome,
    Layout,
    RollbackFailed,
    UpdateAction,
    UpdateFailed,
    UpdateReport,
    rollback,
    stable_layout,
    update,
)
from computer_history.store import Purpose, StoreState, open_store

INTERRUPTED_EXIT_CODE = 130
AGENT_FELL_BACK_EXIT_CODE = 3


@contextmanager
def _reading(database: Path) -> Generator[tuple[sqlite3.Connection | None, str | None]]:
    with open_store(database, Purpose.READ) as store:
        if store.state is StoreState.READY:
            yield store.conn, None
        elif store.state is StoreState.NEWER:
            yield None, "the database's schema is newer than this update reads"
        else:
            yield None, f"the database is {store.state.value}"


def _newest_record(database: Path, spool: Path) -> tuple[datetime | None, bool, str | None]:
    with _reading(database) as (conn, unread):
        found = newest_record(conn, spool, now=formatting.utc_now())
    return (None, False, unread) if found is None else (found.at, found.paused, unread)


def _active_between(
    database: Path, client: AWApi, start: datetime, end: datetime
) -> timedelta | None:
    with _reading(database) as (conn, _):
        return active_time(conn, client, start, end)


def cmd_update(args: argparse.Namespace) -> int:
    layout = stable_layout()
    health = health_path(layout.database)
    client = AWClient(args.aw_url, timeout=AW_CHECK_TIMEOUT_SECONDS)
    try:
        report = update(
            args.host,
            layout,
            last_cycle=lambda: read_health(health),
            newest_record=partial(
                _newest_record, layout.database, default_spool_path(layout.database)
            ),
            active_between=partial(_active_between, layout.database, client),
            now=formatting.utc_now,
            wait_seconds=args.wait,
            sleep=time.sleep,
            monotonic=time.monotonic,
        )
    except UpdateFailed as exc:
        print(f"update failed: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt as exc:
        left = "; ".join(getattr(exc, "__notes__", ())) or NOTHING_CHANGED
        print(f"update interrupted before switching versions ({left})", file=sys.stderr)
        return INTERRUPTED_EXIT_CODE
    for line in format_update(report, layout):
        print(line)
    if report.interrupted:
        return INTERRUPTED_EXIT_CODE
    if report.action is UpdateAction.FELL_BACK:
        return 1
    if report.agent is not None and report.agent.outcome is AgentOutcome.FELL_BACK:
        return AGENT_FELL_BACK_EXIT_CODE
    return 0


def format_update(report: UpdateReport, layout: Layout) -> list[str]:
    """The lines update prints for its report."""
    if report.action is None:
        line = f"Already up to date: version {report.kept} is current"
        if report.behind:
            line += f" (the newest passing commit, {report.version}, is older than current)"
        return [line]
    lines = release_gate_lines(report.skipped)
    if report.action is UpdateAction.UPDATED:
        lines.append(
            f"Updated to version {report.version} (commit {report.commit}) from {report.kept}"
        )
    else:
        lines.append(f"Update to version {report.version} fell back: {report.reason}")
    if report.backup is None:
        lines.append(f"  backup        none (no database at {layout.database} yet)")
    else:
        lines.append(f"  backup        {report.backup.target} (schema v{report.backup.schema})")
    if report.action is UpdateAction.UPDATED:
        lines += [
            "  first cycle   completed; the backend deletes stored spool files again",
            f"  current       {layout.current} -> {layout.versions / report.version}",
            f"  previous      {report.kept} (rollback returns to it)",
        ]
        if report.removed is not None:
            lines.append(f"  removed       {report.removed} (one previous version is kept)")
        if report.agent is not None:
            lines.append(f"  agent         {_agent(report.agent, report.kept)}")
        if report.agent is not None and report.agent.kept is not None:
            lines.append(f"  kept          {report.agent.kept} (the build that fell back)")
    else:
        if report.restored is not None:
            lines.append(f"  restored      {report.restored} (the new version changed the schema)")
        else:
            lines.append("  database      kept as it is (the schema did not change)")
        lines.append(
            f"  backend       restarted on {report.kept}; it reads the spool files it kept again"
        )
    lines += [f"  warning: {problem}" for problem in report.problems]
    return lines


def _agent(agent: AgentCheck, old: str) -> str:
    if agent.outcome is AgentOutcome.UNCHANGED:
        return f"{agent.outcome.value} ({agent.detail})"
    if agent.outcome is AgentOutcome.FELL_BACK:
        return f"fell back to {old}'s capture agent: {agent.detail}"
    return f"{agent.outcome.value}: {agent.detail}"


def cmd_rollback(args: argparse.Namespace) -> int:
    try:
        report = rollback(args.host, stable_layout(), now=formatting.utc_now)
    except RollbackFailed as exc:
        print(f"rollback failed: {exc}", file=sys.stderr)
        return 1
    print(f"Rolled back to version {report.current} from {report.previous}")
    print(f"  previous      {report.previous} (rollback again returns to it)")
    agent = report.agent
    shown = f"moved back to {report.current}'s build" if agent.moved else "not moved"
    print(f"  agent         {shown}" + ("" if agent.why is None else f" ({agent.why})"))
    print("  backend       restarted")
    for problem in report.problems:
        print(f"  warning: {problem}")
    return 0
