"""SQLite connections, explicit transactions and the schema migration runner.

Connections are opened with ``isolation_level=None``: Python's sqlite3 module
never issues an implicit BEGIN or COMMIT. Every multi-statement write goes
through :func:`transaction`, so atomicity is visible at the call site.
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from importlib import resources
from typing import TYPE_CHECKING, NamedTuple

from computer_history.store.paths import resolve_db_path

if TYPE_CHECKING:
    from importlib.resources.abc import Traversable

BUSY_TIMEOUT_SECONDS = 5.0

_MIGRATION_FILENAME = re.compile(r"(\d{3,})_[\w-]+\.sql")

_default_migrations: list[Migration] | None = None


class Migration(NamedTuple):
    version: int
    name: str
    sql: str


def connect(db_path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open the store (creating file and parent directory if needed) and migrate it.

    ``db_path`` is resolved by :func:`resolve_db_path` (flag > env var > default).
    The connection uses WAL journaling, enforces foreign keys, waits up to
    ``BUSY_TIMEOUT_SECONDS`` for locks, and returns :class:`sqlite3.Row` rows.
    """
    path = resolve_db_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT_SECONDS, isolation_level=None)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if mode != "wal":
            raise RuntimeError(f"could not enable WAL journaling on {path} (got {mode!r})")
        migrate(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def connect_readonly(db_path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open an existing store for reading only: no file creation, no migration.

    For diagnostics (``status``): SQLite itself refuses every write
    (``mode=ro``), so callers must check :func:`schema_version` before querying.
    Raises :class:`sqlite3.OperationalError` if the file does not exist.
    """
    path = resolve_db_path(db_path).resolve()
    conn = sqlite3.connect(
        path.as_uri() + "?mode=ro",
        uri=True,
        timeout=BUSY_TIMEOUT_SECONDS,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run the block in one ``BEGIN IMMEDIATE`` transaction; roll back on any error.

    IMMEDIATE takes the write lock up front, so concurrent writers wait (up to the
    busy timeout) at BEGIN instead of failing midway. Not reentrant: nesting raises.
    Expects a connection from :func:`connect` (``isolation_level=None``).
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        # Some errors (e.g. SQLITE_FULL, or a failed COMMIT) already rolled back;
        # don't mask them, but never leave the connection stuck in a transaction.
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def load_migrations(directory: Traversable | None = None) -> list[Migration]:
    """Read ``NNN_description.sql`` files, sorted, checked to run 1..N without gaps.

    Defaults to the ``migrations/`` directory shipped inside this package.
    """
    global _default_migrations
    if directory is None:
        if _default_migrations is not None:
            return list(_default_migrations)
        directory = resources.files(__package__).joinpath("migrations")
        use_cache = True
    else:
        use_cache = False
    migrations = []
    for entry in directory.iterdir():
        if not entry.name.endswith(".sql"):
            continue
        match = _MIGRATION_FILENAME.fullmatch(entry.name)
        if match is None:
            raise RuntimeError(f"migration file {entry.name!r} is not named NNN_description.sql")
        migrations.append(Migration(int(match[1]), entry.name, entry.read_text(encoding="utf-8")))
    migrations = _validate_sequence(migrations)
    if use_cache:
        _default_migrations = list(migrations)
    return migrations


def _validate_sequence(migrations: Sequence[Migration]) -> list[Migration]:
    """Sort and require versions 1..N with no gaps, wherever the list came from."""
    ordered = sorted(migrations)
    versions = [m.version for m in ordered]
    if versions != list(range(1, len(ordered) + 1)):
        raise RuntimeError(f"migrations must be numbered 001, 002, ... with no gaps: {versions}")
    return ordered


def migrate(conn: sqlite3.Connection, migrations: Sequence[Migration] | None = None) -> int:
    """Apply every migration above ``PRAGMA user_version``; return the new version.

    Each migration's statements and its ``user_version`` bump commit together or
    not at all. Migration files must not contain BEGIN/COMMIT/SAVEPOINT.
    """
    migrations = load_migrations() if migrations is None else _validate_sequence(migrations)
    latest = migrations[-1].version if migrations else 0
    current = schema_version(conn)
    if current > latest:
        raise RuntimeError(
            f"database schema version {current} is newer than this code supports ({latest})"
        )
    for migration in migrations:
        if migration.version <= current:
            continue
        with transaction(conn):
            # Re-check under the write lock: another process may have just migrated.
            if schema_version(conn) >= migration.version:
                continue
            for statement in _split_statements(migration.sql):
                conn.execute(statement)
            # PRAGMA values cannot be bound parameters; version is an int from the filename.
            conn.execute(f"PRAGMA user_version = {int(migration.version)}")
    return schema_version(conn)


def _split_statements(script: str) -> list[str]:
    """Split a SQL script into single statements using SQLite's own tokenizer.

    ``executescript()`` is not an option: in Python's legacy transaction mode it
    COMMITs any open transaction before running, which would break atomicity.
    ``sqlite3.complete_statement`` handles semicolons inside strings, comments
    and trigger bodies.
    """
    statements = []
    buffer = ""
    for piece in script.split(";"):
        buffer += piece + ";"
        if sqlite3.complete_statement(buffer):
            if buffer.strip() != ";":
                statements.append(buffer)
            buffer = ""
    # The last piece got a ';' the script never had. What is left is comments
    # (execute() runs them as a no-op) or an unterminated statement (it raises).
    if buffer[:-1].strip():
        statements.append(buffer[:-1])
    return statements
