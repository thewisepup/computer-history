from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from db_states import SUPPORTED, newer_db, outdated_db, user_version, write_locked
from projectors import no_signal

from computer_history.store import (
    Observation,
    Purpose,
    StoreState,
    connect,
    insert_observations,
    open_store,
    schema_version,
    table_counts,
)
from computer_history.store import db as store_db

ALL_PURPOSES = list(Purpose)


def test_ready_database_opens_for_every_purpose(db_path: Path) -> None:
    connect(db_path).close()
    for purpose in ALL_PURPOSES:
        with open_store(db_path, purpose) as store:
            assert store.state is StoreState.READY
            assert store.version == store.supported == SUPPORTED
            assert store.path == db_path
            assert store.conn is not None
            assert schema_version(store.conn) == SUPPORTED


def test_read_purpose_connection_refuses_writes(db_path: Path) -> None:
    connect(db_path).close()
    with open_store(db_path, Purpose.READ) as store:
        assert store.conn is not None
        assert table_counts(store.conn)["observations"] == 0
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            insert_observations(
                store.conn,
                [Observation("s", "1", "2026-11-17T10:00:00Z", "2026-11-17T10:01:00Z", "{}")],
                project=no_signal,
            )


def test_closing_the_store_closes_its_connection(db_path: Path) -> None:
    with open_store(db_path, Purpose.WRITE) as store:
        conn = store.conn
    assert conn is not None
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")


@pytest.mark.parametrize("purpose", [Purpose.READ, Purpose.WRITE_EXISTING])
def test_missing_database_is_reported_and_never_created(tmp_path: Path, purpose: Purpose) -> None:
    path = tmp_path / "nowhere" / "history.db"
    store = open_store(path, purpose)
    assert store.state is StoreState.MISSING
    assert store.conn is None and store.version is None
    assert not path.parent.exists()


def test_write_purpose_creates_a_missing_database(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "history.db"
    with open_store(path, Purpose.WRITE) as store:
        assert store.state is StoreState.READY
    assert user_version(path) == SUPPORTED


def test_read_purpose_refuses_an_outdated_database_without_migrating(db_path: Path) -> None:
    outdated_db(db_path)
    store = open_store(db_path, Purpose.READ)
    assert store.state is StoreState.OUTDATED
    assert (store.version, store.supported) == (SUPPORTED - 1, SUPPORTED)
    assert store.conn is None
    assert user_version(db_path) == SUPPORTED - 1


def test_read_purpose_treats_an_empty_file_as_outdated(db_path: Path) -> None:
    sqlite3.connect(db_path).close()
    store = open_store(db_path, Purpose.READ)
    assert (store.state, store.version) == (StoreState.OUTDATED, 0)


@pytest.mark.parametrize("purpose", [Purpose.WRITE, Purpose.WRITE_EXISTING])
def test_write_purposes_migrate_an_outdated_database(db_path: Path, purpose: Purpose) -> None:
    outdated_db(db_path)
    with open_store(db_path, purpose) as store:
        assert store.state is StoreState.READY
        assert store.conn is not None
        assert schema_version(store.conn) == SUPPORTED


@pytest.mark.parametrize("purpose", ALL_PURPOSES)
def test_newer_database_is_refused_for_every_purpose(db_path: Path, purpose: Purpose) -> None:
    newer_db(db_path)
    store = open_store(db_path, purpose)
    assert store.state is StoreState.NEWER
    assert (store.version, store.supported) == (SUPPORTED + 1, SUPPORTED)
    assert store.conn is None
    assert user_version(db_path) == SUPPORTED + 1


@pytest.mark.parametrize("purpose", [Purpose.WRITE, Purpose.WRITE_EXISTING])
def test_lock_contention_while_opening_for_write_is_busy(
    db_path: Path, purpose: Purpose, quick_busy_timeout: None
) -> None:
    outdated_db(db_path)
    with write_locked(db_path):
        store = open_store(db_path, purpose)
    assert store.state is StoreState.BUSY
    assert store.error == "database is locked"
    assert store.conn is None
    assert user_version(db_path) == SUPPORTED - 1


@pytest.mark.parametrize("purpose", ALL_PURPOSES)
def test_a_held_write_lock_does_not_block_opening_a_ready_database(
    db_path: Path, purpose: Purpose, quick_busy_timeout: None
) -> None:
    connect(db_path).close()
    with write_locked(db_path), open_store(db_path, purpose) as store:
        assert store.state is StoreState.READY


@pytest.mark.parametrize("purpose", ALL_PURPOSES)
def test_a_file_that_is_not_a_database_is_unreadable(db_path: Path, purpose: Purpose) -> None:
    db_path.write_bytes(b"this is not a database, just bytes" * 100)
    store = open_store(db_path, purpose)
    assert store.state is StoreState.UNREADABLE
    assert store.error == "file is not a database"
    assert store.conn is None


class _NoWalConnection(sqlite3.Connection):
    def execute(self, sql: str, *args: object) -> sqlite3.Cursor:
        if sql == "PRAGMA journal_mode = WAL":
            sql = "SELECT 'delete'"
        return super().execute(sql, *args)


@pytest.mark.parametrize("purpose", [Purpose.WRITE, Purpose.WRITE_EXISTING])
def test_a_database_that_cannot_use_wal_is_unreadable_for_write(
    db_path: Path, purpose: Purpose, monkeypatch: pytest.MonkeyPatch
) -> None:
    sqlite3.connect(db_path).close()
    real_connect = sqlite3.connect
    monkeypatch.setattr(
        store_db.sqlite3,
        "connect",
        lambda *args, **kwargs: real_connect(*args, factory=_NoWalConnection, **kwargs),
    )
    store = open_store(db_path, purpose)
    assert store.state is StoreState.UNREADABLE
    assert store.error == f"could not enable WAL journaling on {db_path} (got 'delete')"
    assert store.conn is None
