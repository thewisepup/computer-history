from __future__ import annotations

import json
import re
import sqlite3
import token
import tokenize
from pathlib import Path
from typing import Any

import pytest

from computer_history import cli, synthetic
from computer_history.cli import dev
from computer_history.synthetic import CACHE_ENV_VAR, OPERATIONS, SMALLEST_DATASET


@pytest.fixture(scope="module")
def shared_cache(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("datasets")


@pytest.fixture(autouse=True)
def dataset_cache(monkeypatch: pytest.MonkeyPatch, shared_cache: Path) -> Path:
    monkeypatch.setenv(CACHE_ENV_VAR, str(shared_cache))
    return shared_cache


STRING_TOKENS = {token.STRING, getattr(token, "FSTRING_MIDDLE", token.STRING)}
READ_OPERATION = next(name for name, operation in OPERATIONS.items() if not operation.writes)
OTHER_SQLITE = "0.0.0"


def own_file(folder: Path) -> Path:
    return folder / f"sqlite-{sqlite3.sqlite_version}.json"


def other_file(folder: Path) -> Path:
    return folder / f"sqlite-{OTHER_SQLITE}.json"


def perf(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str]:
    code = cli.main(["dev", "perf", "--dataset", SMALLEST_DATASET, *argv])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def test_updating_writes_a_baseline_that_the_next_run_passes(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    baseline = own_file(tmp_path)
    updated, _ = perf(capsys, "--baseline", str(baseline), "--update-baselines")
    code, printed = perf(capsys, "--baseline", str(baseline))

    assert (updated, code) == (0, 0)
    recorded = json.loads(baseline.read_text())
    assert sorted(recorded) == sorted(OPERATIONS)
    assert all(list(datasets) == [SMALLEST_DATASET] for datasets in recorded.values())
    assert "SQLite " in printed and "passed" in printed
    assert "not VM steps" not in printed
    for name in OPERATIONS:
        assert name in printed


def test_a_costlier_run_fails_naming_the_operation_counter_and_numbers(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    baseline = own_file(tmp_path)
    perf(capsys, "--baseline", str(baseline), "--update-baselines")
    recorded = json.loads(baseline.read_text())
    entry = recorded[READ_OPERATION][SMALLEST_DATASET]
    entry["statements"] -= 1
    baseline.write_text(json.dumps(recorded))

    code, printed = perf(capsys, "--baseline", str(baseline))

    assert code == 1
    expected = f"{READ_OPERATION} on {SMALLEST_DATASET}: statements {entry['statements']:,} -> "
    assert expected in printed and "worse than the baseline" in printed


def test_a_missing_baseline_fails_and_says_how_to_record_one(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    code, printed = perf(capsys, "--baseline", str(own_file(tmp_path / "none")))

    assert code == 1
    assert (
        f"ingest on {SMALLEST_DATASET}: no baseline yet" in printed
        and "--update-baselines" in printed
    )


def test_counters_writes_what_was_measured_in_the_baselines_format(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    counters = tmp_path / "counters.json"
    baseline = own_file(tmp_path)
    perf(capsys, "--baseline", str(baseline), "--update-baselines")
    measured = json.loads(baseline.read_text())
    doctored = json.loads(baseline.read_text())
    doctored[READ_OPERATION][SMALLEST_DATASET]["statements"] -= 1
    doctored[READ_OPERATION]["month"] = kept = measured[READ_OPERATION][SMALLEST_DATASET] | {
        "vm_steps": 7
    }
    baseline.write_text(json.dumps(doctored))

    code, printed = perf(capsys, "--baseline", str(baseline), "--counters", str(counters))

    assert code == 1
    measured[READ_OPERATION]["month"] = kept
    assert json.loads(counters.read_text()) == measured
    assert f"Counters written: {counters}" in printed


def _other_sqlites_baseline(capsys: pytest.CaptureFixture[str], folder: Path) -> dict[str, Any]:
    perf(capsys, "--baseline", str(own_file(folder)), "--update-baselines")
    recorded = json.loads(own_file(folder).read_text())
    for entry in (entry for datasets in recorded.values() for entry in datasets.values()):
        entry["vm_steps"] *= 2
        entry["by_statement"] = {
            text: [runs, 7] for text, (runs, _) in entry["by_statement"].items()
        }
    other_file(folder).write_text(json.dumps(recorded))
    return recorded


def test_on_another_sqlite_the_gate_compares_all_but_vm_steps_and_says_so(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    recorded = _other_sqlites_baseline(capsys, tmp_path)

    passed, printed = perf(capsys, "--baseline", str(other_file(tmp_path)))
    recorded[READ_OPERATION][SMALLEST_DATASET]["statements"] -= 1
    other_file(tmp_path).write_text(json.dumps(recorded))
    failed, _ = perf(capsys, "--baseline", str(other_file(tmp_path)))

    assert (passed, failed) == (0, 1)
    assert (
        f"SQLite {sqlite3.sqlite_version} is not the baseline's {OTHER_SQLITE}: compared"
        " statements, full scans and pages but not VM steps"
    ) in printed


def test_updating_on_another_sqlite_keeps_the_baselines_vm_steps(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    recorded = _other_sqlites_baseline(capsys, tmp_path)
    measured = json.loads(own_file(tmp_path).read_text())
    recorded[READ_OPERATION][SMALLEST_DATASET]["statements"] -= 1
    other_file(tmp_path).write_text(json.dumps(recorded))

    code, printed = perf(capsys, "--baseline", str(other_file(tmp_path)), "--update-baselines")

    assert code == 0
    assert "Baseline rewritten from this run, keeping its VM steps." in printed
    entry = recorded[READ_OPERATION][SMALLEST_DATASET]
    entry["statements"] = measured[READ_OPERATION][SMALLEST_DATASET]["statements"]
    assert json.loads(other_file(tmp_path).read_text()) == recorded


def _message_strings(path: Path) -> list[str]:
    with path.open("rb") as source:
        tokens = tokenize.tokenize(source.readline)
        return [token.string for token in tokens if token.type in STRING_TOKENS]


def test_messages_name_only_flags_that_exist(
    capsys: pytest.CaptureFixture[str],
) -> None:
    usages = ""
    for command in dev.DEV_HANDLERS:
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
