from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from computer_history import cli
from computer_history.synthetic import CACHE_ENV_VAR, OPERATIONS, SMALLEST


@pytest.fixture(scope="module")
def shared_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("datasets")


@pytest.fixture(autouse=True)
def dataset_cache(monkeypatch: pytest.MonkeyPatch, shared_cache: Path) -> Path:
    monkeypatch.setenv(CACHE_ENV_VAR, str(shared_cache))
    return shared_cache


def own_file(folder: Path) -> Path:
    return folder / f"sqlite-{sqlite3.sqlite_version}.json"


def perf(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = cli.main(["dev", "perf", "--dataset", SMALLEST, *argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_updating_writes_a_baseline_that_the_next_run_passes(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    updated, _ = perf(capsys, "--baselines", str(tmp_path), "--update-baselines")
    code, printed = perf(capsys, "--baselines", str(tmp_path))
    baseline = own_file(tmp_path)

    assert (updated, code) == (0, 0)
    recorded = json.loads(baseline.read_text())
    assert sorted(recorded) == sorted(OPERATIONS)
    assert all(list(datasets) == [SMALLEST] for datasets in recorded.values())
    assert "SQLite " in printed and "passed" in printed
    for name in OPERATIONS:
        assert name in printed


def test_a_costlier_run_fails_naming_the_operation_counter_and_numbers(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    perf(capsys, "--baselines", str(tmp_path), "--update-baselines")
    baseline = own_file(tmp_path)
    recorded = json.loads(baseline.read_text())
    entry = recorded["status-reads"][SMALLEST]
    entry["statements"] -= 1
    baseline.write_text(json.dumps(recorded))

    code, printed = perf(capsys, "--baselines", str(tmp_path))

    assert code == 1
    expected = f"status-reads on {SMALLEST}: statements {entry['statements']:,} -> "
    assert expected in printed and "worse than the baseline" in printed


def test_a_missing_baseline_fails_and_says_how_to_record_one(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, printed = perf(capsys, "--baselines", str(tmp_path / "none"))

    assert code == 1
    assert f"ingest on {SMALLEST}: no baseline yet" in printed and "--update-baselines" in printed


def test_counters_writes_what_was_measured_in_the_baselines_format(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    counters = tmp_path / "counters.json"
    perf(capsys, "--baselines", str(tmp_path), "--update-baselines")
    baseline = own_file(tmp_path)
    measured = json.loads(baseline.read_text())
    doctored = json.loads(baseline.read_text())
    doctored["status-reads"][SMALLEST]["statements"] -= 1
    baseline.write_text(json.dumps(doctored))

    code, printed = perf(capsys, "--baselines", str(tmp_path), "--counters", str(counters))

    assert code == 1
    assert json.loads(counters.read_text()) == measured
    assert f"Counters written: {counters}" in printed


def test_without_its_own_sqlites_baseline_the_gate_uses_the_newest_and_says_so(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    perf(capsys, "--baselines", str(tmp_path), "--update-baselines")
    recorded = json.loads(own_file(tmp_path).read_text())
    for entry in (entry for datasets in recorded.values() for entry in datasets.values()):
        entry["sqlite_version"] = "9.0.0"
    own_file(tmp_path).unlink()
    (tmp_path / "sqlite-9.0.0.json").write_text(json.dumps(recorded))
    (tmp_path / "sqlite-1.0.0.json").write_text("{}")

    code, printed = perf(capsys, "--baselines", str(tmp_path))

    assert code == 0
    assert f"Baseline: {tmp_path / 'sqlite-9.0.0.json'}" in printed
    assert "note: entries recorded on SQLite 9.0.0, whose VM steps can differ" in printed
    assert not own_file(tmp_path).exists()
