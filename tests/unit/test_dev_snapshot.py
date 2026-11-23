from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from cli_output import RunCli
from db_states import damaged, integrity, left_with_a_wal, store_windows, stored_ids, writer

from computer_history.cli.profile import NOT_A_CHECKOUT
from computer_history.sources.activitywatch import WINDOW_SOURCE
from computer_history.sources.capture_spool.paths import SPOOL_FOLDER_NAME
from computer_history.store import (
    DATABASE_NAME,
    DB_ENV_VAR,
    INSTALL_MARKER_NAME,
    VERSIONS_FOLDER_NAME,
    connect,
    sidecars,
    supported_version,
)
from computer_history.store import db as store_db

SCREENSHOTS_FOLDER = "screenshots"


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
        store_windows(backend, "after")

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
        f"dev snapshot refused: another process has {dev / DATABASE_NAME} open; stop the"
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
