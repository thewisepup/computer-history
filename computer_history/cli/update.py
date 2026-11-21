from __future__ import annotations

import argparse
import sys

from computer_history.cli import formatting
from computer_history.sources import backend_heartbeat_path, read_backend_heartbeat
from computer_history.stable import (
    RELEASE_GATE,
    RollbackFailed,
    UpdateFailed,
    UpdateOutcome,
    rollback,
    stable_layout,
    update,
    version_name,
)
from computer_history.store import DATABASE_NAME


def cmd_update(args: argparse.Namespace) -> int:
    layout = stable_layout()
    heartbeat = backend_heartbeat_path(layout.live / DATABASE_NAME)
    try:
        report = update(
            args.host,
            layout,
            last_cycle=lambda: read_backend_heartbeat(heartbeat),
            now=formatting.utc_now,
        )
    except UpdateFailed as exc:
        print(f"update failed: {exc}", file=sys.stderr)
        return 1
    if report.outcome is UpdateOutcome.UP_TO_DATE:
        print(f"Already up to date: version {report.kept} is current")
        return 0
    print(f"Release gate: {', '.join(RELEASE_GATE)}")
    for verdict in report.skipped:
        print(f"  skipped {version_name(verdict.commit)}: {verdict.summary}")
    if report.outcome is UpdateOutcome.UPDATED:
        print(f"Updated to version {report.version} (commit {report.commit}) from {report.kept}")
    else:
        print(f"Update to version {report.version} fell back to {report.kept}: {report.reason}")
    if report.backup is None:
        print(f"  backup        none (no database at {layout.live / DATABASE_NAME} yet)")
    else:
        print(f"  backup        {report.backup.target} (schema v{report.backup.schema})")
    if report.outcome is UpdateOutcome.UPDATED:
        print("  first cycle   completed; the backend deletes stored spool files again")
        print(f"  current       {layout.current} -> {layout.versions / report.version}")
        print(f"  previous      {report.kept} (rollback returns to it)")
        if report.removed is not None:
            print(f"  removed       {report.removed} (one previous version is kept)")
    elif report.restored is not None:
        print(f"  restored      {report.restored} (the new version changed the schema)")
    else:
        print("  database      kept as it is (the schema did not change)")
    if report.outcome is UpdateOutcome.FELL_BACK:
        print(f"  backend       restarted on {report.kept}; it reads the spool files it kept again")
    for problem in report.problems:
        print(f"  warning: {problem}")
    return 0 if report.outcome is UpdateOutcome.UPDATED else 1


def cmd_rollback(args: argparse.Namespace) -> int:
    try:
        report = rollback(args.host, stable_layout(), now=formatting.utc_now)
    except RollbackFailed as exc:
        print(f"rollback failed: {exc}", file=sys.stderr)
        return 1
    print(f"Rolled back to version {report.current} from {report.previous}")
    print(f"  previous      {report.previous} (rollback again returns to it)")
    print("  backend       restarted")
    for problem in report.problems:
        print(f"  warning: {problem}")
    return 0
