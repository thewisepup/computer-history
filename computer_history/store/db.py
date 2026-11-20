"""SQLite connections, transactions and the schema migration runner.

Nothing starts a transaction implicitly. Every multi-statement write goes
through transaction().
"""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from importlib import resources
from pathlib import Path
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


class NewerSchema(RuntimeError):
    """The database was migrated by newer code than this."""

    def __init__(self, version: int, supported: int) -> None:
        super().__init__(
            f"database schema version {version} is newer than this code supports ({supported})"
        )
        self.version = version
        self.supported = supported


class WalUnavailable(RuntimeError):
    """SQLite would not switch the database to WAL journaling."""


def connect(
    db_path: str | os.PathLike[str] | None = None, *, create: bool = True
) -> sqlite3.Connection:
    """Open the database for writing and bring its schema up to date.

    Creates the file first unless create is False.
    """
    path = resolve_db_path(db_path)
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = _open(path, "rwc" if create else "rw")
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        if mode != "wal":
            raise WalUnavailable(f"could not enable WAL journaling on {path} (got {mode!r})")
        migrate(conn)
    except BaseException:
        conn.close()
        raise
    return conn


def connect_readonly(db_path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open an existing database for reading only. Fails if the file does not exist."""
    return _open(resolve_db_path(db_path), "ro")


def connect_immutable(db_path: str | os.PathLike[str]) -> sqlite3.Connection:
    """Open a finished database that nothing writes again, for reading only and leaving no files."""
    return _open(Path(db_path), "ro&immutable=1")


def _open(path: Path, mode: str) -> sqlite3.Connection:
    conn = sqlite3.connect(
        f"{path.resolve().as_uri()}?mode={mode}",
        uri=True,
        timeout=BUSY_TIMEOUT_SECONDS,
        isolation_level=None,
    )
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run the block as one transaction, rolling back on any error.

    Takes the write lock up front and cannot be nested.
    """
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise


def schema_version(conn: sqlite3.Connection) -> int:
    return conn.execute("PRAGMA user_version").fetchone()[0]


def supported_version() -> int:
    """The schema version this code migrates databases to."""
    return load_migrations()[-1].version


def load_migrations(directory: Traversable | None = None) -> list[Migration]:
    """Read the numbered migration files from the package's migrations directory."""
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
    ordered = sorted(migrations)
    versions = [m.version for m in ordered]
    if versions != list(range(1, len(ordered) + 1)):
        raise RuntimeError(f"migrations must be numbered 001, 002, ... with no gaps: {versions}")
    return ordered


def migrate(conn: sqlite3.Connection, migrations: Sequence[Migration] | None = None) -> int:
    """Apply every migration the database has not seen yet.

    Each migration commits fully or not at all.
    """
    migrations = load_migrations() if migrations is None else _validate_sequence(migrations)
    latest = migrations[-1].version if migrations else 0
    current = schema_version(conn)
    if current > latest:
        raise NewerSchema(current, latest)
    for migration in migrations:
        if migration.version <= current:
            continue
        with transaction(conn):
            if _applied_by_another_process(conn, migration):
                continue
            for statement in _split_statements(migration.sql):
                conn.execute(statement)
            conn.execute(f"PRAGMA user_version = {int(migration.version)}")
    return schema_version(conn)


def _applied_by_another_process(conn: sqlite3.Connection, migration: Migration) -> bool:
    return schema_version(conn) >= migration.version


def _split_statements(script: str) -> list[str]:
    statements = []
    buffer = ""
    for piece in script.split(";"):
        buffer += piece + ";"
        if sqlite3.complete_statement(buffer):
            if buffer.strip() != ";":
                statements.append(buffer)
            buffer = ""
    if buffer[:-1].strip():
        statements.append(buffer[:-1])
    return statements
