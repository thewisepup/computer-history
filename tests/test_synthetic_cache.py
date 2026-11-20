from __future__ import annotations

import dataclasses
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from computer_history.store import connect, content_digest
from computer_history.synthetic import (
    CACHE_ENV_VAR,
    CachedDataset,
    DatasetInputs,
    build_dataset,
    cache_root,
    cached_dataset,
    copy_dataset,
    dataset_key,
    open_cached,
)
from computer_history.synthetic.cache import PACKAGE

REPO = Path(__file__).resolve().parent.parent

DEVELOPER_DAY = DatasetInputs(persona="developer", scenario="typical", tier="day", seed=1)


def test_a_second_request_reuses_the_entry_without_building(dataset_cache: Path) -> None:
    first = cached_dataset(DEVELOPER_DAY)
    stamp = first.db_path.stat()
    second = cached_dataset(DEVELOPER_DAY)

    assert (first.built, second.built) == (True, False)
    assert second.folder == first.folder
    assert first.folder.parent == dataset_cache
    assert second.db_path.stat().st_ino == stamp.st_ino
    assert second.db_path.stat().st_mtime_ns == stamp.st_mtime_ns


def test_changing_any_input_changes_the_key() -> None:
    others = [
        dataclasses.replace(DEVELOPER_DAY, seed=2),
        dataclasses.replace(DEVELOPER_DAY, start=date(2026, 1, 6)),
        dataclasses.replace(DEVELOPER_DAY, timezone="UTC"),
    ]

    keys = {dataset_key(inputs) for inputs in [DEVELOPER_DAY, *others]}

    assert len(keys) == 1 + len(others)
    assert dataset_key(DEVELOPER_DAY) == dataset_key(dataclasses.replace(DEVELOPER_DAY))


def test_changing_a_source_file_or_migration_of_the_package_changes_the_key(
    tmp_path: Path,
) -> None:
    code = tmp_path / "computer_history"
    shutil.copytree(PACKAGE, code, ignore=shutil.ignore_patterns("__pycache__"))
    before = dataset_key(DEVELOPER_DAY, code)
    module = code / "sources" / "runner.py"
    migration = sorted((code / "store" / "migrations").glob("*.sql"))[-1]

    (code / "cli" / "README.md").write_text("docs only\n")
    after_docs = dataset_key(DEVELOPER_DAY, code)
    module.write_text(module.read_text() + "\n# changed\n")
    after_module = dataset_key(DEVELOPER_DAY, code)
    migration.write_text(migration.read_text() + "\n-- changed\n")
    after_migration = dataset_key(DEVELOPER_DAY, code)

    assert before == dataset_key(DEVELOPER_DAY, PACKAGE)
    assert after_docs == before
    assert len({before, after_module, after_migration}) == 3


def test_a_newer_sqlite_changes_the_key(monkeypatch: pytest.MonkeyPatch) -> None:
    before = dataset_key(DEVELOPER_DAY)
    monkeypatch.setattr(sqlite3, "sqlite_version", "0.0.1")

    assert dataset_key(DEVELOPER_DAY) != before


def test_a_build_that_loses_the_race_discards_its_copy(dataset_cache: Path) -> None:
    rival: list[CachedDataset] = []

    def build_while_a_rival_finishes_first(inputs: DatasetInputs, folder: Path) -> object:
        built = build_dataset(inputs, folder)
        rival.append(cached_dataset(inputs))
        return built

    loser = cached_dataset(DEVELOPER_DAY, build=build_while_a_rival_finishes_first)

    assert rival[0].built and not loser.built
    assert loser.folder == rival[0].folder
    assert _listing(dataset_cache) == [loser.key]
    _assert_complete(loser)


def test_two_processes_building_one_key_leave_one_complete_entry(dataset_cache: Path) -> None:
    builders = [
        subprocess.Popen(
            [sys.executable, "-c", BUILD_IN_A_NEW_PROCESS],
            cwd=REPO,
            stdout=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    folders = {builder.communicate()[0].strip() for builder in builders}

    assert [builder.returncode for builder in builders] == [0, 0]
    entry = cached_dataset(DEVELOPER_DAY)
    assert folders == {str(entry.folder)}
    assert _listing(dataset_cache) == [entry.key]
    _assert_complete(entry)


def test_a_failed_build_leaves_no_entry_and_the_next_request_builds(dataset_cache: Path) -> None:
    def build_then_fail(inputs: DatasetInputs, folder: Path) -> object:
        build_dataset(inputs, folder)
        raise RuntimeError("the build was interrupted")

    with pytest.raises(RuntimeError, match="interrupted"):
        cached_dataset(DEVELOPER_DAY, build=build_then_fail)

    assert _listing(dataset_cache) == []
    entry = cached_dataset(DEVELOPER_DAY)
    assert entry.built
    _assert_complete(entry)


def test_a_cached_database_opens_read_only_and_reading_leaves_the_entry_untouched() -> None:
    entry = cached_dataset(DEVELOPER_DAY)
    before = _listing(entry.folder)
    conn = open_cached(entry)
    try:
        assert conn.execute("SELECT count(*) FROM observations").fetchone()[0] > 0
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("DELETE FROM ingest_progress")
    finally:
        conn.close()

    assert _listing(entry.folder) == before == ["history.db", "manifest.json"]


def test_writers_get_a_copy_and_the_entry_keeps_its_contents(tmp_path: Path) -> None:
    entry = cached_dataset(DEVELOPER_DAY)
    copied = copy_dataset(entry, tmp_path / "scratch")
    conn = connect(tmp_path / "scratch" / "history.db")
    try:
        conn.execute("DELETE FROM ingest_progress")
        changed = content_digest(conn)
    finally:
        conn.close()

    assert [path.name for path in copied] == ["history.db", "manifest.json"]
    assert changed != json.loads(entry.manifest_path.read_text())["content_digest"]
    _assert_complete(entry)


def test_the_cache_lives_in_the_environment_variable_else_the_user_cache_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(CACHE_ENV_VAR, str(tmp_path / "elsewhere"))
    configured = cache_root()
    monkeypatch.delenv(CACHE_ENV_VAR)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    mac = cache_root()
    monkeypatch.setattr(sys, "platform", "linux")
    linux = cache_root()
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    xdg = cache_root()

    assert configured == tmp_path / "elsewhere"
    assert mac == tmp_path / "home" / "Library" / "Caches" / "ComputerHistory" / "datasets"
    assert linux == tmp_path / "home" / ".cache" / "computer-history" / "datasets"
    assert xdg == tmp_path / "xdg" / "computer-history" / "datasets"


BUILD_IN_A_NEW_PROCESS = """
from computer_history.synthetic import DatasetInputs, cached_dataset
inputs = DatasetInputs(persona="developer", scenario="typical", tier="day", seed=1)
print(cached_dataset(inputs).folder)
"""


def _listing(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


def _assert_complete(entry: CachedDataset) -> None:
    manifest = json.loads(entry.manifest_path.read_text())
    conn = open_cached(entry)
    try:
        assert content_digest(conn) == manifest["content_digest"]
    finally:
        conn.close()
