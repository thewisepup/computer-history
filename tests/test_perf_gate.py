from __future__ import annotations

import os
from pathlib import Path

import pytest

from computer_history.synthetic import (
    CACHE_ENV_VAR,
    EXPECTED_SCALING_FAILURES,
    GATE_DATASETS,
    OPERATIONS,
    GateReport,
    cache_root,
    run_gate,
)

pytestmark = pytest.mark.perf
USER_CACHE = os.environ.get(CACHE_ENV_VAR)
LARGER = [label for label in GATE_DATASETS if label != "day"]


@pytest.fixture(autouse=True)
def dataset_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    if USER_CACHE is not None:
        monkeypatch.setenv(CACHE_ENV_VAR, USER_CACHE)


@pytest.fixture(scope="module")
def report(tmp_path_factory: pytest.TempPathFactory) -> GateReport:
    cache = Path(USER_CACHE) if USER_CACHE else cache_root()
    return run_gate(GATE_DATASETS, cache=cache, scratch=tmp_path_factory.mktemp("perf"))


@pytest.mark.parametrize("dataset", list(GATE_DATASETS))
@pytest.mark.parametrize("operation", list(OPERATIONS))
def test_the_operation_costs_what_the_baseline_records(
    report: GateReport, operation: str, dataset: str
) -> None:
    findings = [f for f in report.findings if (f.operation, f.dataset) == (operation, dataset)]

    if findings:
        pytest.fail("\n".join(finding.describe() for finding in findings), pytrace=False)


def _scaling_case(operation: str, label: str) -> object:
    issue = EXPECTED_SCALING_FAILURES.get(operation)
    marks = [pytest.mark.xfail(strict=True, reason=issue)] if issue else []
    return pytest.param(operation, label, marks=marks, id=f"{operation}-{label}")


@pytest.mark.parametrize(
    ("operation", "dataset"),
    [_scaling_case(operation, label) for operation in OPERATIONS for label in LARGER],
)
def test_the_operation_grows_no_faster_than_the_scaling_check_allows(
    report: GateReport, operation: str, dataset: str
) -> None:
    finding = report.expected.get(f"{operation} on {dataset}")
    finding = finding or next(
        (f for f in report.scaling if (f.operation, f.dataset) == (operation, dataset)), None
    )

    if finding is not None:
        pytest.fail(finding.describe(), pytrace=False)
