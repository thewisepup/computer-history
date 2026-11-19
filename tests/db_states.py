from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from computer_history.store import connect, load_migrations, migrate

SUPPORTED = len(load_migrations())


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
