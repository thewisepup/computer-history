from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from computer_history.cli.formatting import human_size
from computer_history.stable import (
    BACKEND,
    BackendRestart,
    RestoreFailed,
    find_daily_backup,
    restore_backup,
    stable_layout,
    take_daily_backup,
)
from computer_history.store import IntegrityCheckFailed

FAILURES = (OSError, IntegrityCheckFailed)


def utc_now() -> datetime:
    return datetime.now(UTC)


def cmd_backup(args: argparse.Namespace) -> int:
    if not args.database.is_file():
        print(f"No database at {args.database} yet: nothing to back up")
        return 0
    try:
        taken = take_daily_backup(args.database, utc_now().astimezone().date())
    except FAILURES as exc:
        print(f"backup failed: {exc}", file=sys.stderr)
        return 1
    if taken.copy is None:
        print(f"Today's backup is already taken: {taken.path}")
    else:
        print(f"Backed up {args.database}")
        print(f"  copied to {taken.copy.target}")
        print(f"  schema v{taken.copy.schema}, {human_size(taken.copy.size)}, integrity ok")
    for path in taken.removed:
        print(f"  removed   {path}")
    return 0


def backup_arg(value: str) -> date | Path:
    """A daily backup's day (YYYY-MM-DD), or the path of a backup or set-aside database."""
    try:
        return date.fromisoformat(value)
    except ValueError:
        return Path(value).expanduser()


def cmd_restore(args: argparse.Namespace) -> int:
    try:
        if isinstance(args.backup, date):
            source = find_daily_backup(args.database, args.backup)
            what = f"the daily backup of {args.backup.isoformat()}"
        else:
            source, what = args.backup, str(args.backup)
        restored = restore_backup(
            args.host,
            stable_layout(),
            args.database,
            source,
            profile=args.profile,
            now=utc_now(),
        )
    except RestoreFailed as exc:
        print(f"restore failed: {exc}", file=sys.stderr)
        return 1
    print(f"Restored {what} into {args.database}")
    print(f"  from          {restored.source}")
    print(f"  set aside     {restored.aside} (never deleted)")
    if restored.backend is BackendRestart.RESTARTED:
        print(f"  backend       {BACKEND.label} stopped, then started again")
    elif restored.backend is BackendRestart.NOT_LOADED:
        print(f"  backend       {BACKEND.label} was not loaded; left stopped")
    return 0
