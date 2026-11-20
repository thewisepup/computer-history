from __future__ import annotations

import json
import re
import sqlite3
import token
import tokenize
from pathlib import Path

import pytest

from computer_history import cli, synthetic
from computer_history.cli import dev
from computer_history.synthetic import CACHE_ENV_VAR, OPERATIONS, SMALLEST_DATASET, baseline_file

pytestmark = pytest.mark.dataset


@pytest.fixture(scope="module")
def shared_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("datasets")


@pytest.fixture(autouse=True)
def dataset_cache(monkeypatch: pytest.MonkeyPatch, shared_cache: Path) -> Path:
    monkeypatch.setenv(CACHE_ENV_VAR, str(shared_cache))
    return shared_cache


STRING_TOKENS = {token.STRING, getattr(token, "FSTRING_MIDDLE", token.STRING)}
READ_OPERATION = next(name for name, operation in OPERATIONS.items() if not operation.writes)


def own_file(folder: Path) -> Path:
    return baseline_file(sqlite3.sqlite_version, folder)


def perf(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = cli.main(["dev", "perf", "--dataset", SMALLEST_DATASET, *argv])
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
    assert all(list(datasets) == [SMALLEST_DATASET] for datasets in recorded.values())
    assert "SQLite " in printed and "passed" in printed
    for name in OPERATIONS:
        assert name in printed


def test_a_costlier_run_fails_naming_the_operation_counter_and_numbers(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    perf(capsys, "--baselines", str(tmp_path), "--update-baselines")
    baseline = own_file(tmp_path)
    recorded = json.loads(baseline.read_text())
    entry = recorded[READ_OPERATION][SMALLEST_DATASET]
    entry["statements"] -= 1
    baseline.write_text(json.dumps(recorded))

    code, printed = perf(capsys, "--baselines", str(tmp_path))

    assert code == 1
    expected = f"{READ_OPERATION} on {SMALLEST_DATASET}: statements {entry['statements']:,} -> "
    assert expected in printed and "worse than the baseline" in printed


def test_a_missing_baseline_fails_and_says_how_to_record_one(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, printed = perf(capsys, "--baselines", str(tmp_path / "none"))

    assert code == 1
    assert (
        f"ingest on {SMALLEST_DATASET}: no baseline yet" in printed
        and "--update-baselines" in printed
    )


def test_counters_writes_what_was_measured_in_the_baselines_format(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    counters = tmp_path / "counters.json"
    perf(capsys, "--baselines", str(tmp_path), "--update-baselines")
    baseline = own_file(tmp_path)
    measured = json.loads(baseline.read_text())
    doctored = json.loads(baseline.read_text())
    doctored[READ_OPERATION][SMALLEST_DATASET]["statements"] -= 1
    doctored[READ_OPERATION]["month"] = kept = measured[READ_OPERATION][SMALLEST_DATASET] | {
        "vm_steps": 7
    }
    baseline.write_text(json.dumps(doctored))

    code, printed = perf(capsys, "--baselines", str(tmp_path), "--counters", str(counters))

    assert code == 1
    measured[READ_OPERATION]["month"] = kept
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
    baseline_file("9.0.0", tmp_path).write_text(json.dumps(recorded))
    baseline_file("1.0.0", tmp_path).write_text("{}")

    code, printed = perf(capsys, "--baselines", str(tmp_path))

    assert code == 0
    assert f"Baseline: {baseline_file('9.0.0', tmp_path)}" in printed
    assert "note: entries recorded on SQLite 9.0.0, whose VM steps can differ" in printed
    assert not own_file(tmp_path).exists()


def test_updating_on_a_new_sqlite_keeps_the_compared_files_other_datasets(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    perf(capsys, "--baselines", str(tmp_path), "--update-baselines")
    recorded = json.loads(own_file(tmp_path).read_text())
    for datasets in recorded.values():
        datasets["year"] = datasets[SMALLEST_DATASET] | {"sqlite_version": "9.0.0"}
    own_file(tmp_path).unlink()
    baseline_file("9.0.0", tmp_path).write_text(json.dumps(recorded))
    counters = tmp_path / "counters.json"

    code, _ = perf(
        capsys, "--baselines", str(tmp_path), "--update-baselines", "--counters", str(counters)
    )

    assert code == 0
    for written in (own_file(tmp_path), counters):
        kept = json.loads(written.read_text())
        assert all(set(datasets) == {SMALLEST_DATASET, "year"} for datasets in kept.values()), (
            written
        )
        assert all(datasets["year"]["sqlite_version"] == "9.0.0" for datasets in kept.values())


def _message_strings(path: Path) -> list[str]:
    with path.open("rb") as source:
        tokens = tokenize.tokenize(source.readline)
        return [token.string for token in tokens if token.type in STRING_TOKENS]


def test_messages_name_only_flags_that_exist(
    capsys: pytest.CaptureFixture[str],
) -> None:
    usages = ""
    for command in ("build-db", "perf", "bench"):
        with pytest.raises(SystemExit):
            cli.main(["dev", command, "--help"])
        usages += capsys.readouterr().out
    sources = [*sorted(Path(synthetic.__file__).parent.glob("*.py")), Path(dev.__file__)]
    flags = {
        flag
        for path in sources
        for text in _message_strings(path)
        for flag in re.findall(r"--[a-z][a-z-]+", text)
    }

    assert {"--force", "--update-baselines"} <= flags
    assert not [f for f in sorted(flags) if not re.search(re.escape(f) + r"(?![a-z-])", usages)]
