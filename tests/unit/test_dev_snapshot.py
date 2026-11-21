from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cli_output import RunCli
from projectors import payload_fields

from computer_history.cli.profile import NOT_A_CHECKOUT
from computer_history.sources import WINDOW_SOURCE
from computer_history.sources.capture_spool.paths import SPOOL_FOLDER_NAME
from computer_history.store import (
    DATABASE_NAME,
    DB_ENV_VAR,
    INSTALL_MARKER_NAME,
    VERSIONS_FOLDER_NAME,
    Observation,
    connect,
    insert_observations,
    sidecars,
    supported_version,
)
from computer_history.store import db as store_db

T0 = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
SCREENSHOTS_FOLDER = "screenshots"


def window(source_id: str, minute: int) -> Observation:
    start = T0 + timedelta(minutes=minute)
    payload = f'{{"app": "Code", "title": "{source_id}"}}'
    return Observation(WINDOW_SOURCE, source_id, start, start + timedelta(minutes=1), payload)


def store(conn: sqlite3.Connection, *source_ids: str) -> None:
    batch = [window(source_id, minute) for minute, source_id in enumerate(source_ids)]
    insert_observations(conn, batch, project=payload_fields)


@contextmanager
def writer(path: Path, *source_ids: str) -> Iterator[sqlite3.Connection]:
    """A live backend's connection: rows committed to the WAL but not checkpointed."""
    conn = connect(path)
    try:
        conn.execute("PRAGMA wal_autocheckpoint = 0")
        store(conn, *source_ids)
        yield conn
    finally:
        conn.close()


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


def test_a_snapshot_copies_what_the_live_database_has_committed_while_a_writer_holds_it(
    run: RunCli, live: Path, dev: Path, checkout: Path
) -> None:
    with writer(live / DATABASE_NAME, "a", "b", "c") as backend:
        backend.execute("BEGIN IMMEDIATE")
        backend.execute(
            "INSERT INTO observations (source, source_id, started_at, ended_at, payload,"
            " ingested_at) VALUES (?, 'uncommitted', '', '', '{}', '')",
            (WINDOW_SOURCE,),
        )

        code, out, err = run(checkout, "dev", "snapshot")

        backend.execute("COMMIT")
        store(backend, "after")

    assert code == 0, err
    copy = dev / DATABASE_NAME
    assert out[0] == f"Profile dev ({NOT_A_CHECKOUT}), database {copy}"
    assert out[1] == f"Snapshot of the live database {live / DATABASE_NAME}"
    assert out[2] == f"  copied to {copy}"
    assert out[3].startswith(f"  schema v{supported_version()}, ")
    assert out[3].endswith(", integrity ok")
    assert stored_ids(copy) == ["a", "b", "c"]
    assert integrity(copy) == ["ok"]
    assert stored_ids(live / DATABASE_NAME) == ["a", "after", "b", "c", "uncommitted"]


def listing(folder: Path) -> dict[str, bytes | None]:
    return {
        path.relative_to(folder).as_posix(): path.read_bytes() if path.is_file() else None
        for path in sorted(folder.rglob("*"))
    }


def test_a_snapshot_copies_neither_the_spool_nor_the_screenshots(
    run: RunCli, live: Path, dev: Path, checkout: Path
) -> None:
    connect(live / DATABASE_NAME).close()
    (live / SPOOL_FOLDER_NAME).mkdir()
    (live / SPOOL_FOLDER_NAME / "20260105T090000.000000Z.jsonl").write_text("waiting\n")
    (live / SCREENSHOTS_FOLDER).mkdir()
    (live / SCREENSHOTS_FOLDER / "a.heic").write_bytes(b"image")
    before = listing(live)

    code, _, err = run(checkout, "dev", "snapshot")

    assert code == 0, err
    assert sorted(path.name for path in dev.iterdir()) == [DATABASE_NAME]
    after = listing(live)
    assert {name: after[name] for name in before} == before
    assert set(after) - set(before) <= {path.name for path in sidecars(live / DATABASE_NAME)}


def left_with_a_wal(path: Path, tmp_path: Path, *source_ids: str) -> None:
    """A database whose last rows sit in a WAL file left beside it, as after a crash."""
    scratch = tmp_path / "scratch" / DATABASE_NAME
    with writer(scratch, *source_ids):
        path.parent.mkdir(parents=True, exist_ok=True)
        for name in (DATABASE_NAME, sidecars(scratch)[0].name):
            (path.parent / name).write_bytes((scratch.parent / name).read_bytes())


def test_a_snapshot_replaces_an_existing_dev_database_only_when_forced(
    run: RunCli, tmp_path: Path, live: Path, dev: Path, checkout: Path
) -> None:
    with writer(live / DATABASE_NAME, "live"):
        pass
    left_with_a_wal(dev / DATABASE_NAME, tmp_path, "old")
    before = listing(dev)

    refused, _, why = run(checkout, "dev", "snapshot")
    after_refusal = listing(dev)
    forced, _, err = run(checkout, "dev", "snapshot", "--force")

    assert refused == 1
    assert why == (
        f"dev snapshot refused: {dev} already holds {DATABASE_NAME}, {DATABASE_NAME}-wal;"
        " pass --force to replace it\n"
    )
    assert after_refusal == before
    assert forced == 0, err
    assert sorted(path.name for path in dev.iterdir()) == [DATABASE_NAME]
    assert stored_ids(dev / DATABASE_NAME) == ["live"]


def test_a_forced_snapshot_is_refused_while_another_process_has_the_dev_database_open(
    run: RunCli, live: Path, dev: Path, checkout: Path
) -> None:
    with writer(live / DATABASE_NAME, "live"):
        pass

    with writer(dev / DATABASE_NAME, "old"):
        code, _, err = run(checkout, "dev", "snapshot", "--force")

    assert code == 1
    assert err == (
        f"dev snapshot refused: another process has {dev / DATABASE_NAME} open; stop the dev"
        " commands using it, such as ingest --watch, and try again\n"
    )
    assert sorted(path.name for path in dev.iterdir()) == [DATABASE_NAME]
    assert stored_ids(dev / DATABASE_NAME) == ["old"]


def test_a_forced_snapshot_that_cannot_take_the_targets_place_puts_the_old_database_back(
    run: RunCli, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, live: Path, checkout: Path
) -> None:
    with writer(live / DATABASE_NAME, "live"):
        pass
    target = tmp_path / "elsewhere" / DATABASE_NAME
    left_with_a_wal(target, tmp_path, "old")
    (target.parent / "notes.txt").write_text("mine\n")

    def refuse(source: object, destination: object) -> None:
        raise PermissionError("the folder is read-only")

    with monkeypatch.context() as patched:
        patched.setattr(os, "replace", refuse)
        code, _, err = run(checkout, "dev", "snapshot", "--force", "--db-path", str(target))

    assert code == 1
    assert err == "dev snapshot failed: PermissionError: the folder is read-only\n"
    assert sorted(path.name for path in target.parent.iterdir()) == [DATABASE_NAME, "notes.txt"]
    assert stored_ids(target) == ["old"]


def test_a_database_created_during_the_copy_is_never_overwritten_without_force(
    run: RunCli, monkeypatch: pytest.MonkeyPatch, live: Path, dev: Path, checkout: Path
) -> None:
    with writer(live / DATABASE_NAME, "live"):
        pass
    opened = store_db.connect_readonly

    def meanwhile_another_dev_run_creates_it(path: Path) -> sqlite3.Connection:
        with writer(dev / DATABASE_NAME, "made meanwhile"):
            pass
        return opened(path)

    monkeypatch.setattr(store_db, "connect_readonly", meanwhile_another_dev_run_creates_it)

    code, _, err = run(checkout, "dev", "snapshot")

    assert code == 1
    assert err == (
        f"dev snapshot refused: {dev} already holds {DATABASE_NAME}; pass --force to replace it\n"
    )
    assert sorted(path.name for path in dev.iterdir()) == [DATABASE_NAME]
    assert stored_ids(dev / DATABASE_NAME) == ["made meanwhile"]


def test_a_snapshot_with_no_live_database_fails_and_creates_nothing(
    run: RunCli, live: Path, dev: Path, checkout: Path
) -> None:
    code, _, err = run(checkout, "dev", "snapshot")

    assert code == 1
    assert err == f"dev snapshot failed: no database at {live / DATABASE_NAME}\n"
    assert not dev.exists()
    assert list(live.iterdir()) == []


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


def test_a_snapshot_that_fails_its_integrity_check_leaves_nothing_behind(
    run: RunCli, live: Path, dev: Path, checkout: Path
) -> None:
    damaged(live / DATABASE_NAME)
    dev.mkdir(parents=True)

    code, _, err = run(checkout, "dev", "snapshot")

    assert code == 1
    assert err.startswith(
        f"dev snapshot failed: the copy of {live / DATABASE_NAME} failed its integrity check: "
    )
    assert "never used" in err
    assert list(dev.iterdir()) == []


def live_target_refusal(target: Path, live: Path, dev: Path) -> str:
    return (
        f"refused: {target} is in the live data folder {live}, and the dev database is never"
        f" there, whichever profile runs. Leave --db-path and ${DB_ENV_VAR} unset to use"
        f" {dev / DATABASE_NAME}.\n"
    )


@pytest.mark.parametrize("given", ["flag", "global flag", "env"])
def test_a_snapshot_is_refused_a_target_in_the_live_folder(
    run: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    live: Path,
    dev: Path,
    checkout: Path,
    given: str,
) -> None:
    with writer(live / DATABASE_NAME, "live"):
        pass
    target = Path(str(live).upper()) / "copy.db"
    argv = ["dev", "snapshot"]
    if given == "flag":
        argv += ["--db-path", str(target)]
    elif given == "global flag":
        argv = ["--db-path", str(target), *argv]
    else:
        monkeypatch.setenv(DB_ENV_VAR, str(target))

    code, out, err = run(checkout, *argv)

    assert code == 1
    assert out == [f"Profile dev ({NOT_A_CHECKOUT}), database refused"]
    assert err == live_target_refusal(target, live, dev)
    assert sorted(path.name for path in live.iterdir()) == [DATABASE_NAME]
    assert not dev.exists()


def test_stable_takes_its_snapshot_into_the_dev_folder_too(
    run: RunCli, live: Path, dev: Path
) -> None:
    version = live / VERSIONS_FOLDER_NAME / "1a2b3c4"
    code = version / "venv" / "lib" / "python3.12" / "site-packages" / "computer_history"
    code.mkdir(parents=True)
    (version / INSTALL_MARKER_NAME).write_text("")
    with writer(live / DATABASE_NAME, "live"):
        pass

    status, out, err = run(code, "dev", "snapshot")
    refused, refusal, why = run(code, "dev", "snapshot", "--db-path", str(live / "copy.db"))

    assert status == 0, err
    assert out[0] == f"Profile stable (version 1a2b3c4), database {dev / DATABASE_NAME}"
    assert stored_ids(dev / DATABASE_NAME) == ["live"]
    assert (refused, refusal) == (1, ["Profile stable (version 1a2b3c4), database refused"])
    assert why == live_target_refusal(live / "copy.db", live, dev)
    assert not (live / "copy.db").exists()
