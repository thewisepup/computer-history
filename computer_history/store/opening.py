from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from computer_history.store.db import (
    NewerSchema,
    WalUnavailable,
    connect,
    connect_readonly,
    schema_version,
    supported_version,
)
from computer_history.store.paths import resolve_db_path


class Purpose(Enum):
    READ = "read"
    WRITE = "write"
    WRITE_EXISTING = "write-existing"


class StoreState(Enum):
    READY = "ready"
    MISSING = "missing"
    OUTDATED = "outdated"
    NEWER = "newer"
    BUSY = "busy"
    UNREADABLE = "unreadable"


@dataclass(frozen=True)
class OpenedStore:
    """The database's state, with an open connection only when it is ready.

    Use it as a context manager to close that connection.
    """

    path: Path
    state: StoreState
    supported: int
    version: int | None = None
    error: str | None = None
    conn: sqlite3.Connection | None = None

    def __enter__(self) -> OpenedStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self.conn is not None:
            self.conn.close()


def open_store(db_path: str | os.PathLike[str] | None, purpose: Purpose) -> OpenedStore:
    """Open the database for reading, writing, or writing only if it already exists.

    Reading never creates or migrates, writing migrates, and a newer schema is always refused.
    """
    path = resolve_db_path(db_path)
    supported = supported_version()
    if purpose is not Purpose.WRITE and not path.exists():
        return OpenedStore(path, StoreState.MISSING, supported)
    try:
        if purpose is Purpose.READ:
            return _open_for_read(path, supported)
        conn = connect(path, create=purpose is Purpose.WRITE)
    except NewerSchema as exc:
        return OpenedStore(path, StoreState.NEWER, supported, version=exc.version)
    except sqlite3.Error as exc:
        state = StoreState.BUSY if _is_busy(exc) else StoreState.UNREADABLE
        return OpenedStore(path, state, supported, error=str(exc))
    except WalUnavailable as exc:
        return OpenedStore(path, StoreState.UNREADABLE, supported, error=str(exc))
    return OpenedStore(path, StoreState.READY, supported, version=supported, conn=conn)


def _open_for_read(path: Path, supported: int) -> OpenedStore:
    conn = connect_readonly(path)
    try:
        version = schema_version(conn)
    except BaseException:
        conn.close()
        raise
    if version == supported:
        return OpenedStore(path, StoreState.READY, supported, version=version, conn=conn)
    conn.close()
    state = StoreState.OUTDATED if version < supported else StoreState.NEWER
    return OpenedStore(path, state, supported, version=version)


def _is_busy(exc: sqlite3.Error) -> bool:
    code = getattr(exc, "sqlite_errorcode", None)
    return code is not None and (code & 0xFF) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
