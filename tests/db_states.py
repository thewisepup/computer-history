from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from projectors import payload_fields

from computer_history.sources import WINDOW_SOURCE
from computer_history.store import (
    DATABASE_NAME,
    Observation,
    Progress,
    connect,
    get_progress,
    insert_observations,
    load_migrations,
    migrate,
    sidecars,
)

SUPPORTED = len(load_migrations())
WINDOWS_START = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)


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


def store_windows(conn: sqlite3.Connection, *source_ids: str) -> None:
    """Store one minute-long aw-window observation per source id, a minute apart."""
    batch = [
        Observation(
            WINDOW_SOURCE,
            source_id,
            WINDOWS_START + timedelta(minutes=minute),
            WINDOWS_START + timedelta(minutes=minute + 1),
            f'{{"app": "Code", "title": "{source_id}"}}',
        )
        for minute, source_id in enumerate(source_ids)
    ]
    insert_observations(conn, batch, project=payload_fields)


@contextmanager
def writer(path: Path, *source_ids: str) -> Iterator[sqlite3.Connection]:
    """A live backend's connection: rows committed to the WAL but not checkpointed."""
    conn = connect(path)
    try:
        conn.execute("PRAGMA wal_autocheckpoint = 0")
        store_windows(conn, *source_ids)
        yield conn
    finally:
        conn.close()


def left_with_a_wal(path: Path, tmp_path: Path, *source_ids: str) -> None:
    """A database whose last rows sit in a WAL file left beside it, as after a crash."""
    scratch = tmp_path / "scratch" / DATABASE_NAME
    with writer(scratch, *source_ids):
        path.parent.mkdir(parents=True, exist_ok=True)
        for name in (DATABASE_NAME, sidecars(scratch)[0].name):
            (path.parent / name).write_bytes((scratch.parent / name).read_bytes())


def stored_ids(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("SELECT source_id FROM observations ORDER BY 1")]
    finally:
        conn.close()


def integrity(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [row[0] for row in conn.execute("PRAGMA integrity_check")]
    finally:
        conn.close()


def damaged(path: Path) -> None:
    """A database whose index pages no longer belong to anything, as damage from outside would."""
    conn = sqlite3.connect(path, isolation_level=None)
    try:
        conn.execute("CREATE TABLE t (x)")
        conn.execute("CREATE INDEX t_x ON t (x)")
        conn.executemany("INSERT INTO t VALUES (?)", [(str(n) * 50,) for n in range(500)])
        conn.execute("PRAGMA writable_schema = ON")
        conn.execute("DELETE FROM sqlite_schema WHERE name = 't_x'")
    finally:
        conn.close()
