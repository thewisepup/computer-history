"""Copies of a database taken with SQLite's online backup while other connections keep writing."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from computer_history.store.db import connect_readonly, schema_version
from computer_history.store.paths import sidecars

PARTIAL_SUFFIX = ".partial"


class DatabaseExists(FileExistsError):
    """The copy's target already holds a database, or its sidecar files."""


class IntegrityCheckFailed(RuntimeError):
    """The copy did not pass SQLite's integrity check."""


@dataclass(frozen=True)
class DatabaseCopy:
    """Where a database was copied, its schema version and its size."""

    target: Path
    schema: int
    size: int


def backup_database(source: Path, target: Path, *, replace: bool = False) -> DatabaseCopy:
    """Copy the committed contents of source into target, reading source without locking it.

    The copy is checked for integrity before it takes target's place, and an existing target is
    replaced only when asked.
    """
    if not source.is_file():
        raise FileNotFoundError(f"no database at {source}")
    in_the_way = [path for path in (target, *sidecars(target)) if path.exists()]
    if in_the_way and not replace:
        names = ", ".join(path.name for path in in_the_way)
        raise DatabaseExists(f"{target.parent} already holds {names}")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=PARTIAL_SUFFIX, dir=target.parent
    )
    os.close(handle)
    partial = Path(name)
    try:
        schema = _copy(source, partial)
        for path in sidecars(target):
            path.unlink(missing_ok=True)
        partial.replace(target)
    finally:
        for path in (partial, *sidecars(partial)):
            path.unlink(missing_ok=True)
    return DatabaseCopy(target, schema, target.stat().st_size)


def _copy(source: Path, partial: Path) -> int:
    reader = connect_readonly(source)
    try:
        copy = sqlite3.connect(partial, isolation_level=None)
        try:
            reader.backup(copy)
            problems = [row[0] for row in copy.execute("PRAGMA integrity_check")]
            if problems != ["ok"]:
                raise IntegrityCheckFailed(
                    f"the copy of {source} failed its integrity check: {'; '.join(problems)}"
                )
            return schema_version(copy)
        finally:
            copy.close()
    finally:
        reader.close()
