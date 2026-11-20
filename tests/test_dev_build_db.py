from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from computer_history import cli
from computer_history.store import DB_ENV_VAR, connect, content_digest
from computer_history.synthetic import PERSONAS, SCENARIOS, TIERS

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
    assert sorted(path.name for path in out.iterdir()) == ["history.db", "manifest.json"]
    assert re.search(rf"database\s+{re.escape(str(out / 'history.db'))}", printed)
    assert re.search(rf"manifest\s+{re.escape(str(out / 'manifest.json'))}", printed)
    assert "built" in printed and "reused" in reprinted
    manifest = json.loads((out / "manifest.json").read_text())
    conn = connect(out / "history.db")
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
    assert sorted(path.name for path in out.iterdir()) == [
        "history.db",
        "manifest.json",
        "notes.txt",
    ]


def test_build_db_refuses_the_default_live_database_and_its_folder(
    capsys: pytest.CaptureFixture[str], home: Path, tmp_path: Path, dataset_cache: Path
) -> None:
    live = home / "Library" / "Application Support" / "ComputerHistory"
    live.mkdir(parents=True)
    (live / "history.db").write_text("real history\n")
    alias = tmp_path / "alias"
    alias.symlink_to(live)

    for out in (live, live / "sub", live / "history.db", alias, alias / "sub"):
        code, _, said = build_db(capsys, *DEVELOPER_DAY, "--out", str(out), "--force")
        assert code == 1, out
        assert "live database" in said, out

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
    assert all(str(live / "history.db") in said for _, _, said in refused)
    assert not live.exists()
    assert allowed == 0
