from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

from computer_history.cli import formatting
from computer_history.cli.formatting import copy_lines
from computer_history.stable import (
    BACKEND,
    BackupFailed,
    DailyOutcome,
    RestoreFailed,
    restore_backup,
    stable_layout,
    take_daily_backup,
)

DAY_ARGUMENT = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def cmd_backup(args: argparse.Namespace) -> int:
    try:
        taken = take_daily_backup(args.database, formatting.utc_now().astimezone().date())
    except BackupFailed as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1
    if taken.outcome is DailyOutcome.NO_DATABASE:
        print(f"No database at {args.database} yet: nothing to back up")
    elif taken.outcome is DailyOutcome.ALREADY_TAKEN:
        print(f"Today's backup is already taken: {taken.path}")
    elif taken.copy is not None:
        print(f"Backed up {args.database}")
        for line in copy_lines(taken.copy):
            print(line)
    for path in taken.removed:
        print(f"  removed   {path}")
    return 0


def backup_arg(value: str) -> date | Path:
    """A daily backup's day written YYYY-MM-DD, or else the path of a backup file."""
    if not DAY_ARGUMENT.match(value):
        return Path(value).expanduser()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a day: {value!r}") from exc


def cmd_restore(args: argparse.Namespace) -> int:
    try:
        restored = restore_backup(
            args.host,
            stable_layout(),
            args.database,
            args.backup,
            now=formatting.utc_now(),
        )
    except RestoreFailed as exc:
        print(f"restore failed: {exc}", file=sys.stderr)
        return 1
    what = f"the daily backup of {args.backup}" if isinstance(args.backup, date) else args.backup
    print(f"Restored {what} into {args.database}")
    print(f"  from          {restored.source}")
    if restored.aside is not None:
        print(f"  set aside     {restored.aside} (never deleted)")
    for agent in restored.restarted:
        print(f"  {agent.name:<13} {agent.label} stopped, then started again")
    if restored.managed and BACKEND not in restored.restarted:
        print(f"  backend       {BACKEND.label} was not loaded; left stopped")
    return 0
