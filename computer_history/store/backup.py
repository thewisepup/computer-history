"""Copies of a database taken with SQLite's online backup while other connections keep writing."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from computer_history.store import db
from computer_history.store.paths import SHARED_MEMORY_SUFFIX, existing_database_files, sidecars

PARTIAL_SUFFIX = ".partial"
REPLACED_SUFFIX = ".replaced"


class DatabaseExists(FileExistsError):
    """The copy's target already holds a database, or its sidecar files."""


class DatabaseInUse(RuntimeError):
    """Another connection has the database the copy would replace open."""


class IntegrityCheckFailed(RuntimeError):
    """The copy did not pass SQLite's integrity check."""


@dataclass(frozen=True)
class DatabaseCopy:
    """Where a database was copied, its schema version and its size."""

    target: Path
    schema: int
    size: int


@dataclass(frozen=True)
class RestoredCopy:
    """The copy put in place, and where the database it replaced was moved, when there was one."""

    copy: DatabaseCopy
    aside: Path | None


def backup_database(source: Path, target: Path, *, replace: bool = False) -> DatabaseCopy:
    """Copy the committed contents of source into target, reading source without locking it.

    The copy is checked for integrity before it takes target's place, and an existing target is
    replaced only when asked and when nothing has it open.
    """
    if not source.is_file():
        raise FileNotFoundError(f"no database at {source}")
    _refuse_existing(target, replace)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=PARTIAL_SUFFIX, dir=target.parent
    )
    os.close(handle)
    partial = Path(name)
    try:
        schema = _copy(source, partial)
        if replace:
            _swap_in(partial, target)
        else:
            _link_in(partial, target)
    finally:
        for path in (partial, *sidecars(partial)):
            path.unlink(missing_ok=True)
    return DatabaseCopy(target, schema, target.stat().st_size)


def restore_database(source: Path, target: Path, aside: Path) -> RestoredCopy:
    """Copy source into target's place, moving the database there to aside first."""
    if not source.is_file():
        raise FileNotFoundError(f"no database at {source}")
    if existing_database_files(aside):
        raise DatabaseExists(f"{aside.parent} already holds {aside.name}")
    moved: list[tuple[Path, Path]] = []
    with _held(target, fold_wal=True):
        if target.exists() or target.is_symlink():
            aside.parent.mkdir(parents=True, exist_ok=True)
            target.rename(aside)
            moved.append((target, aside))
    for journal, aside_journal in zip(sidecars(target), sidecars(aside), strict=True):
        if not (journal.exists() or journal.is_symlink()):
            continue
        if moved and not journal.name.endswith(SHARED_MEMORY_SUFFIX):
            journal.rename(aside_journal)
            moved.append((journal, aside_journal))
        else:
            journal.unlink()
    try:
        copy = backup_database(source, target)
    except BaseException:
        for path, to in reversed(moved):
            if not (path.exists() or path.is_symlink()):
                to.rename(path)
        raise
    return RestoredCopy(copy, aside if moved else None)


def _refuse_existing(target: Path, replace: bool) -> None:
    in_the_way = existing_database_files(target)
    if not in_the_way:
        return
    if not replace:
        names = ", ".join(path.name for path in in_the_way)
        raise DatabaseExists(f"{target.parent} already holds {names}")
    _refuse_in_use(target)


def _refuse_in_use(target: Path) -> None:
    with _held(target):
        pass


@contextmanager
def _held(target: Path, *, fold_wal: bool = False) -> Generator[None]:
    """Hold target's exclusive lock, or raise DatabaseInUse while another connection has it open.

    With fold_wal the WAL is checkpointed into the file and removed.
    """
    if not target.is_file():
        yield
        return
    conn = sqlite3.connect(target, isolation_level=None, timeout=0)
    try:
        try:
            conn.execute("PRAGMA locking_mode = EXCLUSIVE")
            conn.execute("BEGIN EXCLUSIVE")
            conn.execute("ROLLBACK")
            if fold_wal:
                conn.execute("PRAGMA journal_mode = DELETE")
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode != sqlite3.SQLITE_BUSY:
                raise
            raise DatabaseInUse(
                f"another process has {target} open; stop the commands using it, such as"
                " ingest --watch, and try again"
            ) from exc
        except sqlite3.DatabaseError:
            pass
        yield
    finally:
        conn.close()


def _copy(source: Path, partial: Path) -> int:
    reader = db.connect_readonly(source)
    try:
        copy = sqlite3.connect(partial, isolation_level=None)
        try:
            reader.backup(copy)
            problems = [row[0] for row in copy.execute("PRAGMA integrity_check")]
            if problems != ["ok"]:
                raise IntegrityCheckFailed(
                    f"the copy of {source} failed its integrity check: {'; '.join(problems)}"
                )
            copy.execute("PRAGMA journal_mode = DELETE")
            return db.schema_version(copy)
        finally:
            copy.close()
    finally:
        reader.close()


def _link_in(partial: Path, target: Path) -> None:
    _refuse_existing(target, replace=False)
    try:
        os.link(partial, target)
    except FileExistsError as exc:
        raise DatabaseExists(f"{target.parent} already holds {target.name}") from exc


def _swap_in(partial: Path, target: Path) -> None:
    _refuse_in_use(target)
    aside = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.", suffix=REPLACED_SUFFIX, dir=target.parent)
    )
    moved: list[Path] = []
    try:
        for path in existing_database_files(target):
            path.rename(aside / path.name)
            moved.append(path)
        os.replace(partial, target)
    except BaseException:
        for path in reversed(moved):
            (aside / path.name).rename(path)
        aside.rmdir()
        raise
    shutil.rmtree(aside)
