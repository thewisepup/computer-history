from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from store_answers import DATASET_FILES

from computer_history import cli
from computer_history.cli import dev
from computer_history.sources import SPOOL_ENV_VAR, resolve_spool_path
from computer_history.store import DB_ENV_VAR, connect, content_digest
from computer_history.store.db import WalUnavailable
from computer_history.synthetic import (
    DATABASE_NAME,
    HEAVY,
    MANIFEST_NAME,
    PERSONAS,
    SCENARIOS,
    TIERS,
)
from computer_history.synthetic.spool import RENDERED_SPOOL_FOLDER

DEVELOPER_DAY = ("--persona", "developer", "--scenario", "typical", "--tier", "day", "--seed", "1")


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    folder = tmp_path / "home"
    monkeypatch.setenv("HOME", str(folder))
    return folder


def build_db(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(["dev", "build-db", *argv])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_build_db_copies_the_dataset_out_and_prints_where_it_landed(
    capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    out = tmp_path / "dev"
    code, printed, _ = build_db(capsys, *DEVELOPER_DAY, "--out", str(out))
    again, reprinted, _ = build_db(capsys, *DEVELOPER_DAY, "--out", str(tmp_path / "again"))

    assert (code, again) == (0, 0)
    spool = out / RENDERED_SPOOL_FOLDER
    assert sorted(path.name for path in out.iterdir()) == DATASET_FILES
    assert re.search(rf"database\s+{re.escape(str(out / DATABASE_NAME))}", printed)
    assert re.search(rf"manifest\s+{re.escape(str(out / MANIFEST_NAME))}", printed)
    assert re.search(rf"{RENDERED_SPOOL_FOLDER}/\s+{re.escape(str(spool))}", printed)
    assert "built" in printed and "reused" in reprinted
    manifest = json.loads((out / MANIFEST_NAME).read_text())
    conn = connect(out / DATABASE_NAME)
    try:
        assert content_digest(conn) == manifest["content_digest"]
    finally:
        conn.close()
    assert manifest["inputs"]["seed"] == 1


def test_every_dataset_input_is_an_option_with_the_registries_as_choices(
    capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["dev", "build-db", "--help"])
    usage = capsys.readouterr().out
    code, _, _ = build_db(
        capsys,
        *DEVELOPER_DAY,
        "--start",
        "2026-03-02",
        "--timezone",
        "UTC",
        "--out",
        str(tmp_path / "dev"),
    )
    with pytest.raises(SystemExit) as unknown:
        cli.main(
            [
                "dev",
                "build-db",
                *DEVELOPER_DAY[:-4],
                "--tier",
                "decade",
                "--seed",
                "1",
                "--out",
                str(tmp_path / "never"),
            ]
        )

    for name in [*PERSONAS, *SCENARIOS, *TIERS]:
        assert name in usage
    assert code == 0
    inputs = json.loads((tmp_path / "dev" / "manifest.json").read_text())["inputs"]
    assert (inputs["start"], inputs["timezone"]) == ("2026-03-02", "UTC")
    assert unknown.value.code == 2
    assert "invalid choice: 'decade'" in capsys.readouterr().err


def test_build_db_refuses_an_existing_output_unless_forced(
    capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    out = tmp_path / "dev"
    build_db(capsys, *DEVELOPER_DAY, "--out", str(out))
    (out / "manifest.json").write_text("mine\n")
    (out / "history.db-wal").write_text("stale\n")
    (out / "notes.txt").write_text("keep me\n")

    refused, _, said = build_db(capsys, *DEVELOPER_DAY, "--out", str(out))
    kept = (out / "manifest.json").read_text()
    forced, _, _ = build_db(capsys, *DEVELOPER_DAY, "--out", str(out), "--force")

    assert refused == 1
    assert "--force" in said and "manifest.json" in said
    assert kept == "mine\n"
    assert forced == 0
    assert json.loads((out / "manifest.json").read_text())["inputs"]["persona"] == "developer"
    assert sorted(path.name for path in out.iterdir()) == sorted([*DATASET_FILES, "notes.txt"])


def test_build_db_refuses_the_default_live_database_and_its_folder(
    capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path, dataset_cache: Path
) -> None:
    live = home / "Library" / "Application Support" / "ComputerHistory"
    live.mkdir(parents=True)
    (live / "history.db").write_text("real history\n")
    alias = tmp_path / "alias"
    alias.symlink_to(live)
    shouted = Path(str(live).upper())

    for out in (live, live / "sub", live / "history.db", alias, alias / "sub", shouted):
        code, _, said = build_db(capsys, *DEVELOPER_DAY, "--out", str(out), "--force")
        assert code == 1, out
        assert "holds the live database" in said, out

    assert sorted(path.name for path in live.iterdir()) == ["history.db"]
    assert (live / "history.db").read_text() == "real history\n"
    assert list(dataset_cache.iterdir()) == []


def test_build_db_refuses_the_database_environment_variable_and_its_folder(
    capsys: pytest.CaptureFixture[str],
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    live = tmp_path / "elsewhere"
    monkeypatch.setenv(DB_ENV_VAR, str(live / "history.db"))

    refused = [
        build_db(capsys, *DEVELOPER_DAY, "--out", str(out), "--force")
        for out in (live, live / "sub", live / "history.db")
    ]
    allowed, _, _ = build_db(capsys, *DEVELOPER_DAY, "--out", str(tmp_path / "dev"))

    assert [code for code, _, _ in refused] == [1, 1, 1]
    assert all(f"in {live}, which holds the live database" in said for _, _, said in refused)
    assert not live.exists()
    assert allowed == 0


def test_build_db_refuses_to_replace_a_folder_that_holds_the_live_database(
    capsys: pytest.CaptureFixture[str],
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = tmp_path / "dev"
    live = out / RENDERED_SPOOL_FOLDER / "live" / "history.db"
    live.parent.mkdir(parents=True)
    live.write_text("real history\n")
    monkeypatch.setenv(DB_ENV_VAR, str(live))

    code, _, said = build_db(capsys, *DEVELOPER_DAY, "--out", str(out), "--force")

    assert code == 1
    assert f"{out / RENDERED_SPOOL_FOLDER} holds {live.parent}" in said
    assert live.read_text() == "real history\n"


def test_build_db_refuses_the_folder_of_a_database_given_with_db_path(
    capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path
) -> None:
    live = tmp_path / "data" / "history.db"
    code = cli.main(
        ["--db-path", str(live), "dev", "build-db", *DEVELOPER_DAY, "--out", str(live.parent)]
    )

    assert code == 1
    assert "holds the live database" in capsys.readouterr().err
    assert not live.parent.exists()


def test_build_db_never_replaces_the_configured_live_spool(
    capsys: pytest.CaptureFixture[str],
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spool = tmp_path / "data" / "spool"
    spool.mkdir(parents=True)
    (spool / "20260105T090000.000000Z.jsonl").write_text("waiting\n")
    monkeypatch.setenv(SPOOL_ENV_VAR, str(spool))

    inside, _, said = build_db(capsys, *DEVELOPER_DAY, "--out", str(spool / "dev"), "--force")

    assert inside == 1
    assert str(spool) in said
    assert [path.name for path in spool.iterdir()] == ["20260105T090000.000000Z.jsonl"]


def test_a_database_already_in_the_output_is_refused_before_anything_is_built(
    capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path, dataset_cache: Path
) -> None:
    out = tmp_path / "dev"
    out.mkdir()
    (out / "history.db").write_text("mine\n")

    code, _, said = build_db(capsys, *DEVELOPER_DAY, "--out", str(out))

    assert code == 1
    assert "already holds history.db" in said
    assert list(dataset_cache.iterdir()) == []


def test_a_database_that_cannot_be_opened_fails_with_a_message_not_a_traceback(
    capsys: pytest.CaptureFixture[str],
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_wal(*args: object, **kwargs: object) -> None:
        raise WalUnavailable("journal_mode stayed delete")

    monkeypatch.setattr(dev, "make_dev_database", no_wal)

    code, _, said = build_db(capsys, *DEVELOPER_DAY, "--out", str(tmp_path / "dev"))

    assert code == 1
    assert said == "dev build-db failed: WalUnavailable: journal_mode stayed delete\n"


def test_heavy_alone_picks_the_heavy_factor_and_takes_another_when_given() -> None:
    parser = cli.build_parser()
    base = ["dev", "build-db", *DEVELOPER_DAY, "--out", "/tmp/unused"]

    bare = parser.parse_args([*base, "--heavy"])
    given = parser.parse_args([*base, "--heavy", "3"])
    left_out = parser.parse_args(base)

    assert (bare.heavy, given.heavy) == (HEAVY, 3.0)
    assert "heavy" not in left_out


def test_status_on_the_copied_database_finds_no_spool_files_waiting(
    capsys: pytest.CaptureFixture[str],
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(SPOOL_ENV_VAR, raising=False)
    out = tmp_path / "dev"
    build_db(capsys, *DEVELOPER_DAY, "--out", str(out))

    code = cli.main(
        ["status", "--db-path", str(out / DATABASE_NAME), "--aw-url", "http://127.0.0.1:1"]
    )
    printed = capsys.readouterr().out

    spool = resolve_spool_path(None, out / DATABASE_NAME)
    assert code == 0
    assert f"0 finished files waiting, 0 in unreadable/  ({spool})" in printed
