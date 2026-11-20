import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from computer_history.store import (
    DB_ENV_VAR,
    Migration,
    connect,
    default_db_path,
    load_migrations,
    migrate,
    resolve_db_path,
    schema_version,
    transaction,
    utc_iso,
)

TABLES = {
    "observations",
    "signals",
    "projects",
    "work_types",
    "blocks",
    "block_tags",
    "reviews",
    "suggestions",
    "ingest_progress",
    "classification_runs",
}
VIEWS = {"block_evidence_v"}
DEFAULT_TAIL = Path("Application Support", "ComputerHistory", "history.db")
LATEST = len(load_migrations())


def schema_objects(conn: sqlite3.Connection, kind: str) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = ? AND name NOT LIKE 'sqlite_%'", (kind,)
    )
    return {row["name"] for row in rows}


def schema_sql(conn: sqlite3.Connection) -> list[tuple[str, str]]:
    return conn.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall()


def raw_connection(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path, isolation_level=None)


@pytest.mark.schema_rule
def test_fresh_db_has_full_schema(conn: sqlite3.Connection) -> None:
    assert schema_objects(conn, "table") == TABLES
    assert schema_objects(conn, "view") == VIEWS
    assert schema_version(conn) == LATEST


def test_connection_settings(conn: sqlite3.Connection) -> None:
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000
    row = conn.execute("SELECT 1 AS one").fetchone()
    assert row["one"] == 1


def test_creates_parent_directory(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "dir" / "history.db"
    connect(path).close()
    assert path.is_file()


@pytest.mark.schema_rule
def test_observations_unique_on_source_and_source_id(conn: sqlite3.Connection) -> None:
    insert_observation(conn, source_id="42")
    with pytest.raises(sqlite3.IntegrityError):
        insert_observation(conn, source_id="42")


@pytest.mark.schema_rule
@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE observations SET payload = '{}' WHERE id = ?",
        "DELETE FROM observations WHERE id = ?",
    ],
    ids=["update", "delete"],
)
def test_observations_are_immutable(conn: sqlite3.Connection, sql: str) -> None:
    obs_id = insert_observation(conn, source_id="42")
    before = conn.execute("SELECT * FROM observations").fetchall()
    with pytest.raises(sqlite3.IntegrityError, match="observations are immutable"):
        conn.execute(sql, (obs_id,))
    assert conn.execute("SELECT * FROM observations").fetchall() == before


def test_reopen_is_noop(db_path: Path) -> None:
    first = connect(db_path)
    insert_observation(first, source_id="1")
    before = schema_sql(first)
    first.close()

    second = connect(db_path)
    assert schema_sql(second) == before
    assert schema_version(second) == LATEST
    assert second.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 1
    second.close()


def test_migrate_again_is_noop(conn: sqlite3.Connection) -> None:
    before = schema_sql(conn)
    assert migrate(conn) == LATEST
    assert schema_sql(conn) == before


def test_two_open_connections_to_same_file(db_path: Path) -> None:
    a = connect(db_path)
    b = connect(db_path)
    insert_observation(a, source_id="from-a")
    assert b.execute("SELECT source_id FROM observations").fetchone()[0] == "from-a"
    a.close()
    b.close()


def test_newer_schema_version_is_refused(db_path: Path) -> None:
    connect(db_path).close()
    raw = raw_connection(db_path)
    raw.execute(f"PRAGMA user_version = {LATEST + 1}")
    raw.close()
    with pytest.raises(RuntimeError, match="newer than this code supports"):
        connect(db_path)


FAILS_HALFWAY = """
CREATE TABLE half_applied (id INTEGER PRIMARY KEY);
INSERT INTO half_applied (id) VALUES (1);
INSERT INTO no_such_table (id) VALUES (1);
"""


def test_failing_migration_leaves_previous_state_untouched(db_path: Path) -> None:
    connect(db_path).close()
    raw = raw_connection(db_path)
    before = schema_sql(raw)
    broken = [*load_migrations(), Migration(LATEST + 1, "002_broken.sql", FAILS_HALFWAY)]

    with pytest.raises(sqlite3.OperationalError, match="no_such_table"):
        migrate(raw, broken)

    assert schema_version(raw) == LATEST
    assert schema_sql(raw) == before
    assert not raw.in_transaction
    raw.close()


def test_failing_first_migration_leaves_db_empty(db_path: Path) -> None:
    raw = raw_connection(db_path)
    good_sql = load_migrations()[0].sql
    broken = [Migration(1, "001_broken.sql", good_sql + FAILS_HALFWAY)]

    with pytest.raises(sqlite3.OperationalError, match="no_such_table"):
        migrate(raw, broken)

    assert schema_version(raw) == 0
    assert schema_sql(raw) == []
    raw.close()


def test_later_migration_applies_in_order(conn: sqlite3.Connection) -> None:
    extra = Migration(LATEST + 1, "002_extra.sql", "CREATE TABLE extra (x TEXT); -- trailing")
    assert migrate(conn, [*load_migrations(), extra]) == LATEST + 1
    assert "extra" in schema_objects(conn, "table")


def test_migration_files_must_be_contiguous(tmp_path: Path) -> None:
    (tmp_path / "001_a.sql").write_text("SELECT 1;")
    (tmp_path / "003_c.sql").write_text("SELECT 1;")
    with pytest.raises(RuntimeError, match="no gaps"):
        load_migrations(tmp_path)


@pytest.mark.schema_rule
def test_signal_without_observation_is_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute(
            "INSERT INTO signals (observation_id, source, started_at, ended_at) "
            "VALUES (999, 'aw-window', ?, ?)",
            ("2026-11-17T10:00:00Z", "2026-11-17T10:01:00Z"),
        )


def test_transaction_rolls_back_on_error(conn: sqlite3.Connection) -> None:
    with pytest.raises(ZeroDivisionError), transaction(conn):
        insert_observation(conn, source_id="doomed")
        raise ZeroDivisionError
    assert not conn.in_transaction
    assert conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0] == 0


def test_block_evidence_is_signals_overlapping_half_open_range(
    conn: sqlite3.Connection,
) -> None:
    block_id = conn.execute(
        "INSERT INTO blocks (started_at, ended_at, status, created_at, updated_at) "
        "VALUES ('2026-11-17T10:00:00Z', '2026-11-17T10:05:00Z', 'auto', 'now', 'now')"
    ).lastrowid
    cases = {
        "overlaps-start": ("2026-11-17T09:58:00Z", "2026-11-17T10:01:00Z"),
        "inside": ("2026-11-17T10:02:00Z", "2026-11-17T10:03:00Z"),
        "instant-at-start": ("2026-11-17T10:00:00Z", "2026-11-17T10:00:00Z"),
        "ends-at-start": ("2026-11-17T09:55:00Z", "2026-11-17T10:00:00Z"),
        "starts-at-end": ("2026-11-17T10:05:00Z", "2026-11-17T10:06:00Z"),
    }
    for source_id, (started, ended) in cases.items():
        obs_id = insert_observation(conn, source_id=source_id, started=started, ended=ended)
        conn.execute(
            "INSERT INTO signals (observation_id, source, started_at, ended_at, title) "
            "VALUES (?, 'aw-window', ?, ?, ?)",
            (obs_id, started, ended, source_id),
        )
    rows = conn.execute(
        "SELECT title FROM block_evidence_v WHERE block_id = ?", (block_id,)
    ).fetchall()
    assert {row["title"] for row in rows} == {"overlaps-start", "inside", "instant-at-start"}


def test_utc_iso_canonicalizes_mixed_spellings() -> None:
    same_instant = [
        "2026-11-17T10:00:00Z",
        "2026-11-17T10:00:00+00:00",
        "2026-11-17T10:00:00.000000Z",
        "2026-11-17T11:00:00+01:00",
        datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC),
    ]
    assert {utc_iso(value) for value in same_instant} == {"2026-11-17T10:00:00.000000Z"}


def test_utc_iso_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        utc_iso(datetime(2026, 11, 17, 10, 0, 0))
    with pytest.raises(ValueError, match="timezone-aware"):
        utc_iso("2026-11-17T10:00:00")


def test_migrate_rejects_unsorted_or_gapped_caller_lists(conn: sqlite3.Connection) -> None:
    gapped = [*load_migrations(), Migration(LATEST + 2, "003_gap.sql", "SELECT 1;")]
    with pytest.raises(RuntimeError, match="no gaps"):
        migrate(conn, gapped)


def test_path_flag_wins_over_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(DB_ENV_VAR, str(tmp_path / "env.db"))
    assert resolve_db_path(tmp_path / "flag.db") == tmp_path / "flag.db"


def test_path_env_wins_over_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(DB_ENV_VAR, str(tmp_path / "env.db"))
    assert resolve_db_path() == tmp_path / "env.db"
    assert resolve_db_path(None) == tmp_path / "env.db"


def test_path_default_under_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert resolve_db_path() == tmp_path / "Library" / DEFAULT_TAIL


def test_path_empty_values_count_as_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(DB_ENV_VAR, "")
    assert resolve_db_path("") == default_db_path() == tmp_path / "Library" / DEFAULT_TAIL


def test_path_expands_user(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert resolve_db_path("~/x.db") == tmp_path / "x.db"



def insert_observation(
    conn: sqlite3.Connection,
    *,
    source_id: str,
    started: str = "2026-11-17T10:00:00Z",
    ended: str = "2026-11-17T10:01:00Z",
) -> int:
    row_id = conn.execute(
        "INSERT INTO observations (source, source_id, started_at, ended_at, payload, ingested_at) "
        "VALUES ('aw-window', ?, ?, ?, '{}', ?)",
        (source_id, started, ended, ended),
    ).lastrowid
    assert row_id is not None
    return row_id
