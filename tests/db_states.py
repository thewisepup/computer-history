from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from computer_history.store import Progress, connect, get_progress, load_migrations, migrate

SUPPORTED = len(load_migrations())


def stored_progress(conn: sqlite3.Connection, source: str) -> Progress:
    """The source's stored ingest progress, failing the test if it has none."""
    progress = get_progress(conn, source)
    assert progress is not None, f"no stored progress for {source}"
    return progress


def outdated_db(path: Path) -> Path:
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        migrate(conn, load_migrations()[:-1])
    finally:
        conn.close()
    return path


def newer_db(path: Path) -> Path:
    connect(path).close()
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute(f"PRAGMA user_version = {SUPPORTED + 1}")
    finally:
        conn.close()
    return path


def corrupt_payloads(conn: sqlite3.Connection, where: str, params: tuple[object, ...]) -> None:
    """Break the JSON of matching observations, as damage from outside the app would."""
    conn.execute("DROP TRIGGER IF EXISTS observations_no_update")
    conn.execute(f"UPDATE observations SET payload = '{{not json' WHERE {where}", params)


def user_version(path: Path) -> int:
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


@contextmanager
def write_locked(path: Path) -> Iterator[None]:
    locker = sqlite3.connect(path, isolation_level=None)
    try:
        locker.execute("BEGIN IMMEDIATE")
        yield
        locker.execute("ROLLBACK")
    finally:
        locker.close()
