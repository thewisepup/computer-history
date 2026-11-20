from __future__ import annotations

import json
from pathlib import Path

import pytest

from computer_history import cli
from computer_history.cli import status
from computer_history.synthetic import CACHE_ENV_VAR, OPERATIONS
from computer_history.synthetic import operations as gate_operations


@pytest.fixture(scope="module")
def shared_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("datasets")


@pytest.fixture(autouse=True)
def dataset_cache(monkeypatch: pytest.MonkeyPatch, shared_cache: Path) -> Path:
    monkeypatch.setenv(CACHE_ENV_VAR, str(shared_cache))
    return shared_cache


def perf(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = cli.main(["dev", "perf", "--dataset", "day", *argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_updating_writes_a_baseline_that_the_next_run_passes(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    baseline = tmp_path / "baseline.json"

    updated, _ = perf(capsys, "--baseline", str(baseline), "--update-baselines")
    code, printed = perf(capsys, "--baseline", str(baseline))

    assert (updated, code) == (0, 0)
    recorded = json.loads(baseline.read_text())
    assert sorted(recorded["operations"]) == sorted(OPERATIONS)
    assert all(list(datasets) == ["day"] for datasets in recorded["operations"].values())
    assert "SQLite " in printed and "passed" in printed
    for name in OPERATIONS:
        assert name in printed


def test_a_costlier_run_fails_naming_the_operation_counter_and_numbers(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    baseline = tmp_path / "baseline.json"
    perf(capsys, "--baseline", str(baseline), "--update-baselines")
    recorded = json.loads(baseline.read_text())
    entry = recorded["operations"]["status-reads"]["day"]
    entry["statements"] -= 1
    baseline.write_text(json.dumps(recorded))

    code, printed = perf(capsys, "--baseline", str(baseline))

    assert code == 1
    expected = f"status-reads on day: statements {entry['statements']:,} -> "
    assert expected in printed and "worse than the baseline" in printed


def test_a_missing_baseline_fails_and_says_how_to_record_one(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, printed = perf(capsys, "--baseline", str(tmp_path / "none.json"))

    assert code == 1
    assert "ingest on day: no baseline yet" in printed and "--update-baselines" in printed


def test_the_status_reads_use_the_window_and_gap_length_status_prints() -> None:
    assert gate_operations.STATUS_WINDOW == status.STATUS_WINDOW
    assert gate_operations.MIN_GAP_SECONDS == status.MIN_GAP_SECONDS
