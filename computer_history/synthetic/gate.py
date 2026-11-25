"""The performance gate: each operation's costs on fixed datasets against a committed baseline."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType

from computer_history.store import SqliteBuild, sqlite_build
from computer_history.synthetic.baseline import (
    BASELINE,
    Key,
    baseline_sqlite,
    load_baseline,
    recorded,
    save_baseline,
    with_vm_steps_of,
    without_vm_steps,
)
from computer_history.synthetic.cache import cached_dataset, open_cached
from computer_history.synthetic.generate import HEAVY, DatasetInputs
from computer_history.synthetic.meter import Costs, Scan, StatementCost
from computer_history.synthetic.operations import (
    OPERATIONS,
    GateDataset,
    Operation,
    gate_dataset,
    measure_operation,
)

UPDATE_HINT = "run `computer-history dev perf --update-baselines` and say why in the pull request"
VM_STEP_TOLERANCE = 0.02
WINDOWED_GROWTH = 2.0
EVENT_GROWTH_SLACK = 1.5
SMALLEST_DATASET = "day"
SHOWN_STATEMENTS = 5


def _inputs(tier: str, heavy: float = 1.0) -> DatasetInputs:
    return DatasetInputs("developer", "messy", tier, 1, heavy=heavy)


GATE_DATASETS: Mapping[str, DatasetInputs] = MappingProxyType(
    {"day": _inputs("day"), "month": _inputs("month")}
)
NIGHTLY_DATASETS: Mapping[str, DatasetInputs] = MappingProxyType(
    {"year": _inputs("year"), "heavy-year": _inputs("year", HEAVY)}
)
PERF_DATASETS: Mapping[str, DatasetInputs] = MappingProxyType({**GATE_DATASETS, **NIGHTLY_DATASETS})


def perf_datasets(labels: Sequence[str] | None) -> dict[str, DatasetInputs]:
    """The datasets named, each once in the order given, or the pull-request gate's by default."""
    return {label: PERF_DATASETS[label] for label in dict.fromkeys(labels or GATE_DATASETS)}


SCAN_ALLOWLIST: Mapping[re.Pattern[str], str] = MappingProxyType(
    {
        re.compile(r'SELECT COUNT\(\*\) FROM "\w+"$'): "status prints every table's row count",
        re.compile(r"SELECT name FROM sqlite_master "): "status lists the tables it counts",
        re.compile(r"WITH obs AS \( SELECT source, COUNT\(\*\)"): (
            "status prints each source's totals over all of history"
        ),
        re.compile(r"SELECT COUNT\(\*\) FROM (observations|signals)$"): (
            "rebuild-signals compares the signals before and after"
        ),
        re.compile(r"SELECT DISTINCT source FROM observations "): (
            "rebuild-signals checks every stored source has an adapter"
        ),
        re.compile(r"SELECT id, source, started_at, ended_at, payload FROM observations "): (
            "rebuild-signals reprojects every observation"
        ),
    }
)
EXPECTED_SCALING_FAILURES: Mapping[str, str] = MappingProxyType(
    {
        "status-reads": "https://github.com/thewisepup/open-computer-history/issues/84",
        "capture-health": "https://github.com/thewisepup/open-computer-history/issues/84",
        "screenshot-health": "https://github.com/thewisepup/open-computer-history/issues/84",
    }
)
UNEXPECTED_PASS_HINT = "take it off EXPECTED_SCALING_FAILURES in computer_history/synthetic/gate.py"


class FindingKind(Enum):
    COUNTER = "counter"
    NO_BASELINE = "no baseline"
    STALE_BASELINE = "stale baseline"
    SCAN_NOT_ALLOWED = "scan not allowed"
    SCANS_CHANGED = "scans changed"
    SCALING = "scaling"


@dataclass(frozen=True)
class Finding:
    """One way an operation's costs on a dataset differ from what the gate allows."""

    kind: FindingKind
    operation: str
    dataset: str
    counter: str = ""
    before: object = None
    after: object = None
    cheaper: bool = False
    grew: tuple[str, ...] = ()

    def describe(self) -> str:
        """The finding as lines a person reads in a failed check."""
        where = f"{self.operation} on {self.dataset}:"
        if self.kind is FindingKind.NO_BASELINE:
            lines = [f"{where} no baseline yet: {UPDATE_HINT}"]
        elif self.kind is FindingKind.STALE_BASELINE:
            lines = [f"{where} the baseline has costs for an operation that is gone: {UPDATE_HINT}"]
        elif self.kind is FindingKind.SCAN_NOT_ALLOWED:
            lines = [f"{where} {self.after} is not on the scan allowlist"]
        elif self.kind is FindingKind.SCANS_CHANGED:
            lines = [
                f"{where} full scans differ from the baseline:"
                f" new {self.after}, gone {self.before}: {UPDATE_HINT}"
            ]
        elif self.kind is FindingKind.SCALING:
            lines = [
                f"{where} {self.after:,} VM steps, over the {self.before:,}"
                f" the {SMALLEST_DATASET} dataset allows"
            ]
        else:
            change = f"{where} {self.counter} {_change(self.before, self.after)}"
            verdict = (
                f"cheaper than the baseline: {UPDATE_HINT}"
                if self.cheaper
                else "worse than the baseline"
            )
            lines = [f"{change}, {verdict}"]
        if self.grew:
            lines.append("  statements that changed most:")
            lines += [f"    {line}" for line in self.grew]
        return "\n".join(lines)


def _change(before: object, after: object) -> str:
    if isinstance(before, int) and isinstance(after, int):
        percent = f" ({(after - before) / before:+.1%})" if before else ""
        return f"{before:,} -> {after:,}{percent}"
    return f"{before} -> {after}"


def allowed(statement: str) -> bool:
    """Whether the statement may scan a whole table by design."""
    return any(pattern.match(statement) for pattern in SCAN_ALLOWLIST)


def compare(
    operation: Operation, dataset: str, measured: Costs, baseline: Costs | None
) -> list[Finding]:
    """Every way the costs differ from the baseline past tolerance, and every scan not allowed."""
    name = operation.name
    found = [
        Finding(
            FindingKind.SCAN_NOT_ALLOWED,
            name,
            dataset,
            after=f"SCAN {scan.table} in {scan.statement}",
        )
        for scan in measured.full_scans
        if not allowed(scan.statement)
    ]
    if baseline is None:
        return [*found, Finding(FindingKind.NO_BASELINE, name, dataset)]
    measured, baseline = recorded(operation, measured), recorded(operation, baseline)
    grew = _grew(baseline.by_statement, measured.by_statement)
    if measured.statements != baseline.statements:
        found.append(
            _counter(name, dataset, "statements", baseline.statements, measured.statements, grew)
        )
    if abs(measured.vm_steps - baseline.vm_steps) > VM_STEP_TOLERANCE * baseline.vm_steps:
        found.append(
            _counter(name, dataset, "vm_steps", baseline.vm_steps, measured.vm_steps, grew)
        )
    gone = set(baseline.full_scans) - set(measured.full_scans)
    new = set(measured.full_scans) - set(baseline.full_scans)
    if gone or new:
        found.append(
            Finding(
                FindingKind.SCANS_CHANGED,
                name,
                dataset,
                "full scans",
                _scans(gone),
                _scans(new),
                cheaper=not new,
            )
        )
    if measured.pages != baseline.pages:
        found.append(_counter(name, dataset, "pages", baseline.pages, measured.pages))
    for table in sorted(measured.table_pages.keys() | baseline.table_pages.keys()):
        before, after = baseline.table_pages.get(table, 0), measured.table_pages.get(table, 0)
        if before != after:
            found.append(_counter(name, dataset, f"pages of {table}", before, after))
    return found


def _counter(
    operation: str, dataset: str, counter: str, before: int, after: int, grew: tuple[str, ...] = ()
) -> Finding:
    return Finding(
        FindingKind.COUNTER, operation, dataset, counter, before, after, after < before, grew
    )


def _scans(scans: Iterable[Scan]) -> str:
    return "; ".join(sorted(f"{scan.table} in {scan.statement}" for scan in scans)) or "none"


def _grew(
    before: Mapping[str, StatementCost], after: Mapping[str, StatementCost]
) -> tuple[str, ...]:
    none = StatementCost(0, 0)
    changes: list[tuple[int, int, str]] = []
    for text in before.keys() | after.keys():
        old, new = before.get(text, none), after.get(text, none)
        if old != new:
            changes.append((-abs(new.runs - old.runs), -abs(new.vm_steps - old.vm_steps), text))
    return tuple(
        f"{before.get(text, none).runs:,} -> {after.get(text, none).runs:,} runs,"
        f" {before.get(text, none).vm_steps:,} -> {after.get(text, none).vm_steps:,} VM steps:"
        f" {text}"
        for _, _, text in sorted(changes)[:SHOWN_STATEMENTS]
    )


def scaling(
    operation: Operation,
    dataset: str,
    smallest: tuple[Costs, int],
    larger: tuple[Costs, int],
) -> Finding | None:
    """A finding if the operation's VM steps grow faster from the smallest dataset than allowed."""
    (small, small_events), (large, large_events) = smallest, larger
    before, after = _scaled(operation, small), _scaled(operation, large)
    steps = sum(cost.vm_steps for cost in before.values())
    if operation.windowed:
        limit = WINDOWED_GROWTH * steps
    else:
        limit = EVENT_GROWTH_SLACK * steps * large_events / small_events
    measured = sum(cost.vm_steps for cost in after.values())
    if measured <= limit:
        return None
    return Finding(
        FindingKind.SCALING,
        operation.name,
        dataset,
        "vm_steps",
        round(limit),
        measured,
        grew=_grew(before, after),
    )


def _scaled(operation: Operation, costs: Costs) -> Mapping[str, StatementCost]:
    if not operation.windowed:
        return costs.by_statement
    return {text: cost for text, cost in costs.by_statement.items() if not allowed(text)}


@dataclass(frozen=True)
class GateReport:
    """What one gate run measured, on which SQLite, and every finding against the baseline."""

    build: SqliteBuild
    baseline: Path
    baseline_sqlite: str
    measured: Mapping[Key, Costs]
    findings: tuple[Finding, ...]
    scaling: tuple[Finding, ...]
    expected: Mapping[Key, Finding | None]
    scaling_checked: bool

    @property
    def failures(self) -> tuple[Finding, ...]:
        """Findings that fail the gate: baseline differences and unexpected scaling."""
        return self.findings + self.scaling

    @property
    def unexpected_passes(self) -> tuple[Key, ...]:
        """Operations and datasets expected to fail the scaling check that passed it."""
        return tuple(key for key, finding in self.expected.items() if finding is None)

    @property
    def ok(self) -> bool:
        return not self.failures and not self.unexpected_passes

    @property
    def compares_vm_steps(self) -> bool:
        """Whether the run's SQLite is the baseline's, so VM steps can be compared too."""
        return self.build.version == self.baseline_sqlite


def run_gate(
    datasets: Mapping[str, DatasetInputs],
    *,
    cache: Path,
    scratch: Path,
    baseline: Path = BASELINE,
    update: bool = False,
    counters: Path | None = None,
) -> GateReport:
    """Measure every operation on every dataset against the baseline, rewritten first on update.

    On another SQLite than the baseline's, VM steps are neither compared nor updated.
    """
    gated = {
        label: gate_dataset(inputs, cached_dataset(inputs, cache))
        for label, inputs in datasets.items()
    }
    build = _build(next(iter(gated.values())))
    measured = {
        (name, label): measure_operation(operation, dataset, scratch / label / name)
        for label, dataset in gated.items()
        for name, operation in OPERATIONS.items()
    }
    version = baseline_sqlite(baseline)
    same = build.version == version
    kept = load_baseline(baseline)
    written = (
        measured
        if same
        else {key: with_vm_steps_of(costs, kept.get(key)) for key, costs in measured.items()}
    )
    if counters is not None:
        save_baseline(counters, written, keep=kept)
    if update:
        save_baseline(baseline, written, keep=kept)
    compared = load_baseline(baseline)
    findings: list[Finding] = []
    for (name, label), costs in measured.items():
        before = compared.get((name, label))
        if not same and before is not None:
            costs, before = without_vm_steps(costs), without_vm_steps(before)
        findings += compare(OPERATIONS[name], label, costs, before)
    findings += [
        Finding(FindingKind.STALE_BASELINE, name, label)
        for name, label in compared
        if name not in OPERATIONS
    ]
    scaled: list[Finding] = []
    expected: dict[Key, Finding | None] = {}
    larger = sorted(gated.keys() - {SMALLEST_DATASET}) if SMALLEST_DATASET in gated else []
    for label in larger:
        for name, operation in OPERATIONS.items():
            finding = scaling(
                operation,
                label,
                (measured[(name, SMALLEST_DATASET)], gated[SMALLEST_DATASET].observations),
                (measured[(name, label)], gated[label].observations),
            )
            if name in EXPECTED_SCALING_FAILURES:
                expected[(name, label)] = finding
            elif finding is not None:
                scaled.append(finding)
    return GateReport(
        build,
        baseline,
        version,
        measured,
        tuple(findings),
        tuple(scaled),
        expected,
        scaling_checked=bool(larger),
    )


def _build(dataset: GateDataset) -> SqliteBuild:
    conn = open_cached(dataset.entry)
    try:
        return sqlite_build(conn)
    finally:
        conn.close()
