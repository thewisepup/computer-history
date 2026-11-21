from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import cast

import pytest

from computer_history import cli
from computer_history.synthetic import (
    CACHE_ENV_VAR,
    OPERATIONS,
    SLOWDOWN_TOLERANCE,
    SMALLEST_DATASET,
    GateDataset,
    Operation,
    Timing,
    time_operation,
)
from computer_history.synthetic.operations import Session


def test_more_than_a_quarter_slower_than_the_baseline_is_flagged() -> None:
    assert not Timing("ingest", "day", median=1.25, baseline=1.0).slower
    assert Timing("ingest", "day", median=1.26, baseline=1.0).slower
    assert not Timing("ingest", "day", median=0.5, baseline=1.0).slower
    assert not Timing("ingest", "day", median=9.0, baseline=None).slower
    assert Timing("ingest", "day", median=1.5, baseline=1.2).change == pytest.approx(0.25)


def test_an_operation_is_timed_five_times_in_scratch_it_leaves_behind(tmp_path: Path) -> None:
    ticks: Iterator[float] = iter([0, 3, 10, 11, 20, 25, 30, 32, 40, 44])
    started: list[Path] = []

    def start(dataset: GateDataset, folder: Path) -> Session:
        folder.mkdir(parents=True)
        started.append(folder)
        return Session(sqlite3.connect(":memory:"), lambda: None)

    times = time_operation(
        Operation("fake", start), cast(GateDataset, None), tmp_path / "fake", clock=ticks.__next__
    )

    assert times == (3, 1, 5, 2, 4)
    assert len(set(started)) == len(times)
    assert list(tmp_path.iterdir()) == []


@pytest.fixture(scope="module")
def shared_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("datasets")


@pytest.fixture(autouse=True)
def dataset_cache(monkeypatch: pytest.MonkeyPatch, shared_cache: Path) -> Path:
    monkeypatch.setenv(CACHE_ENV_VAR, str(shared_cache))
    return shared_cache


def bench(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = cli.main(["dev", "bench", "--dataset", SMALLEST_DATASET, *argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_a_first_run_records_the_machines_baseline_and_the_next_compares_with_it(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    baseline = tmp_path / "bench.json"

    first, recorded = bench(capsys, "--baseline", str(baseline))
    second, compared = bench(capsys, "--baseline", str(baseline))

    assert (first, second) == (0, 0)
    assert sorted(json.loads(baseline.read_text())) == sorted(OPERATIONS)
    assert recorded.count("recorded") == len(OPERATIONS)
    assert "slower" not in recorded
    assert "No baseline on this machine yet: these medians become it, nothing compared." in recorded
    assert "recorded" not in compared and "%" in compared
    for name in OPERATIONS:
        assert name in compared


def test_a_slowdown_is_flagged_and_still_exits_zero(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    baseline = tmp_path / "bench.json"
    bench(capsys, "--baseline", str(baseline))
    recorded = json.loads(baseline.read_text())
    recorded["status-reads"][SMALLEST_DATASET] /= 10
    baseline.write_text(json.dumps(recorded))

    code, printed = bench(capsys, "--baseline", str(baseline))

    assert code == 0
    flagged = [line for line in printed.splitlines() if line.endswith("SLOWER")]
    assert [line.split()[:2] for line in flagged] == [["status-reads", SMALLEST_DATASET]]
    assert (
        f"1 timing more than {SLOWDOWN_TOLERANCE:.0%} slower than this machine's baseline"
        in printed
    )


def test_timings_new_to_the_baseline_are_counted_apart_from_the_compared(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    baseline = tmp_path / "bench.json"
    bench(capsys, "--baseline", str(baseline))
    recorded = json.loads(baseline.read_text())
    del recorded["ingest"]
    baseline.write_text(json.dumps(recorded))

    _, printed = bench(capsys, "--baseline", str(baseline))

    compared = len(OPERATIONS) - 1
    tolerance = f"{SLOWDOWN_TOLERANCE:.0%}"
    assert (
        f"Nothing more than {tolerance} slower than this machine's baseline, of {compared}"
        in printed
    )
    assert "1 timing had no baseline and was recorded." in printed


def test_updating_says_the_baseline_was_rewritten_not_that_there_was_none(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    baseline = tmp_path / "bench.json"
    bench(capsys, "--baseline", str(baseline))

    _, printed = bench(capsys, "--baseline", str(baseline), "--update-baselines")

    assert "Baseline rewritten from these medians, nothing compared." in printed
    assert "No baseline" not in printed
