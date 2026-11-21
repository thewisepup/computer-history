from __future__ import annotations

import argparse
import sys

from computer_history.cli import formatting
from computer_history.sources import health_path, read_health
from computer_history.stable import (
    NOTHING_CHANGED,
    RELEASE_GATE,
    Layout,
    RollbackFailed,
    UpdateAction,
    UpdateFailed,
    UpdateReport,
    rollback,
    stable_layout,
    update,
    version_name,
)

INTERRUPTED_EXIT_CODE = 130


def cmd_update(args: argparse.Namespace) -> int:
    layout = stable_layout()
    health = health_path(layout.database)
    try:
        report = update(
            args.host,
            layout,
            last_cycle=lambda: read_health(health),
            now=formatting.utc_now,
            wait_seconds=args.wait,
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
    return 1 if report.action is UpdateAction.FELL_BACK else 0


def format_update(report: UpdateReport, layout: Layout) -> list[str]:
    """The lines update prints for its report."""
    if report.action is None:
        line = f"Already up to date: version {report.kept} is current"
        if report.behind:
            line += f" (the newest passing commit, {report.version}, is older than current)"
        return [line]
    lines = [f"Release gate: {', '.join(RELEASE_GATE)}"]
    lines += [f"  skipped {version_name(v.commit)}: {v.summary}" for v in report.skipped]
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
