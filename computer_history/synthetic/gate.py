"""The performance gate: each operation's costs on fixed datasets against a committed baseline."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType

from computer_history.store import SqliteBuild, sqlite_build
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

BASELINE_PATH = Path(__file__).with_name("perf_baseline.json")
UPDATE_HINT = "run `computer-history dev perf --update-baselines` and say why in the pull request"
VM_STEP_TOLERANCE = 0.02
WINDOWED_GROWTH = 2.0
EVENT_GROWTH_SLACK = 1.5
SMALLEST = "day"
SHOWN_STATEMENTS = 5


def _inputs(tier: str, heavy: float = 1.0) -> DatasetInputs:
    return DatasetInputs("developer", "messy", tier, 1, heavy=heavy)


GATE_DATASETS: Mapping[str, DatasetInputs] = MappingProxyType(
    {"day": _inputs("day"), "month": _inputs("month")}
)
NIGHTLY_DATASETS: Mapping[str, DatasetInputs] = MappingProxyType(
    {"year": _inputs("year"), "heavy-year": _inputs("year", HEAVY)}
)

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
        "status-reads": "https://github.com/thewisepup/computer-history/issues/84",
        "capture-health": "https://github.com/thewisepup/computer-history/issues/84",
    }
)


@dataclass(frozen=True)
class Finding:
    """One way an operation's costs on a dataset differ from what the gate allows."""

    operation: str
    dataset: str
    counter: str
    before: object
    after: object
    cheaper: bool = False
    grew: tuple[str, ...] = ()

    def describe(self) -> str:
        """The finding as lines a person reads in a failed check."""
        head = (
            f"{self.operation} on {self.dataset}: {self.counter} {_change(self.before, self.after)}"
        )
        if self.counter == "baseline":
            lines = [f"{self.operation} on {self.dataset}: no baseline yet: {UPDATE_HINT}"]
        elif self.counter == "full scans":
            lines = [
                f"{self.operation} on {self.dataset}: full scans differ from the baseline:"
                f" new {self.after}, gone {self.before}: {UPDATE_HINT}"
            ]
        elif self.counter == "full scan":
            lines = [
                f"{self.operation} on {self.dataset}: {self.after} is not on the scan allowlist"
            ]
        elif self.counter == "scaling":
            lines = [
                f"{self.operation} on {self.dataset}: {self.after:,} VM steps, over the"
                f" {self.before:,} the day tier allows"
            ]
        elif self.cheaper:
            lines = [f"{head}, cheaper than the baseline: {UPDATE_HINT}"]
        else:
            lines = [f"{head}, worse than the baseline"]
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


def recorded(operation: Operation, costs: Costs) -> Costs:
    """The costs the gate keeps for the operation: pages only for one that writes."""
    return costs if operation.writes else replace(costs, pages=0, table_pages={})


def compare(
    operation: Operation, dataset: str, measured: Costs, baseline: Costs | None
) -> list[Finding]:
    """Every way the costs differ from the baseline past tolerance, and every scan not allowed."""
    found = [
        Finding(
            operation.name, dataset, "full scan", None, f"SCAN {scan.table} in {scan.statement}"
        )
        for scan in measured.full_scans
        if not allowed(scan.statement)
    ]
    if baseline is None:
        return [*found, Finding(operation.name, dataset, "baseline", None, "missing")]
    measured, baseline = recorded(operation, measured), recorded(operation, baseline)
    grew = _grew(baseline.by_statement, measured.by_statement)
    if measured.statements != baseline.statements:
        found.append(
            _finding(
                operation, dataset, "statements", baseline.statements, measured.statements, grew
            )
        )
    if abs(measured.vm_steps - baseline.vm_steps) > VM_STEP_TOLERANCE * baseline.vm_steps:
        found.append(
            _finding(operation, dataset, "vm_steps", baseline.vm_steps, measured.vm_steps, grew)
        )
    if set(measured.full_scans) != set(baseline.full_scans):
        found.append(
            Finding(
                operation.name,
                dataset,
                "full scans",
                _scans(set(baseline.full_scans) - set(measured.full_scans)),
                _scans(set(measured.full_scans) - set(baseline.full_scans)),
                cheaper=len(measured.full_scans) < len(baseline.full_scans),
            )
        )
    if measured.pages != baseline.pages:
        found.append(_finding(operation, dataset, "pages", baseline.pages, measured.pages))
    for name in sorted(measured.table_pages.keys() | baseline.table_pages.keys()):
        before, after = baseline.table_pages.get(name, 0), measured.table_pages.get(name, 0)
        if before != after:
            found.append(_finding(operation, dataset, f"pages of {name}", before, after))
    return found


def _finding(
    operation: Operation,
    dataset: str,
    counter: str,
    before: int,
    after: int,
    grew: tuple[str, ...] = (),
) -> Finding:
    return Finding(operation.name, dataset, counter, before, after, after < before, grew)


def _scans(scans: Iterable[Scan]) -> str:
    return "; ".join(sorted(f"{scan.table} in {scan.statement}" for scan in scans)) or "none"


def _grew(
    before: Mapping[str, StatementCost], after: Mapping[str, StatementCost]
) -> tuple[str, ...]:
    none = StatementCost(0, 0)
    changes = []
    for text in before.keys() | after.keys():
        old, new = before.get(text, none), after.get(text, none)
        if old != new:
            changes.append((-abs(new.count - old.count), -abs(new.vm_steps - old.vm_steps), text))
    return tuple(
        f"{before.get(text, none).count:,} -> {after.get(text, none).count:,} runs,"
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
    """A finding if the operation's VM steps grow faster from the day tier than the gate allows.

    A windowed read may cost twice its day cost without allowed scans, others grow with events.
    """
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
        operation.name, dataset, "scaling", round(limit), measured, grew=_grew(before, after)
    )


def _scaled(operation: Operation, costs: Costs) -> Mapping[str, StatementCost]:
    if not operation.windowed:
        return costs.by_statement
    return {text: cost for text, cost in costs.by_statement.items() if not allowed(text)}


@dataclass(frozen=True)
class Baseline:
    """The committed costs, by operation and dataset, and the SQLite build they were recorded on."""

    build: SqliteBuild | None
    costs: Mapping[tuple[str, str], Costs]


def load_baseline(path: Path) -> Baseline:
    """The baseline in the file, or an empty one if there is no file."""
    if not path.exists():
        return Baseline(None, {})
    data = json.loads(path.read_text(encoding="utf-8"))
    costs = {
        (operation, dataset): Costs(
            statements=entry["statements"],
            vm_steps=entry["vm_steps"],
            full_scans=tuple(Scan(*scan) for scan in entry["full_scans"]),
            pages=entry["pages"],
            table_pages=entry["table_pages"],
            by_statement={
                text: StatementCost(*cost) for text, cost in entry["by_statement"].items()
            },
        )
        for operation, datasets in data["operations"].items()
        for dataset, entry in datasets.items()
    }
    build = SqliteBuild(data["sqlite_version"], tuple(data["compile_options"]))
    return Baseline(build, costs)


def save_baseline(
    path: Path,
    build: SqliteBuild,
    costs: Mapping[tuple[str, str], Costs],
    keep: Baseline | None = None,
) -> None:
    """Write the costs to the file over the kept baseline's other entries, with the build."""
    merged = {**(keep.costs if keep is not None else {}), **costs}
    operations: dict[str, dict[str, object]] = {}
    for (name, dataset), measured in sorted(merged.items()):
        entry = recorded(OPERATIONS[name], measured)
        operations.setdefault(name, {})[dataset] = {
            "statements": entry.statements,
            "vm_steps": entry.vm_steps,
            "full_scans": sorted(list(scan) for scan in entry.full_scans),
            "pages": entry.pages,
            "table_pages": dict(sorted(entry.table_pages.items())),
            "by_statement": {text: list(cost) for text, cost in sorted(entry.by_statement.items())},
        }
    data = {
        "sqlite_version": build.version,
        "compile_options": list(build.compile_options),
        "operations": operations,
    }
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class GateReport:
    """What one gate run measured, on which SQLite, and every finding against the baseline."""

    build: SqliteBuild
    baseline_build: SqliteBuild | None
    measured: Mapping[tuple[str, str], Costs]
    events: Mapping[str, int]
    findings: tuple[Finding, ...]
    scaling: tuple[Finding, ...]
    expected: Mapping[str, Finding | None]

    @property
    def failures(self) -> tuple[Finding, ...]:
        """Findings that fail the gate: baseline differences and unexpected scaling."""
        return self.findings + self.scaling

    @property
    def unexpected_passes(self) -> tuple[str, ...]:
        """Operations expected to fail the scaling check that passed it."""
        return tuple(name for name, finding in self.expected.items() if finding is None)

    @property
    def ok(self) -> bool:
        return not self.failures and not self.unexpected_passes


def run_gate(
    datasets: Mapping[str, DatasetInputs],
    *,
    cache: Path,
    scratch: Path,
    baseline_path: Path = BASELINE_PATH,
    update: bool = False,
) -> GateReport:
    """Measure every operation on every dataset against the baseline, rewriting it first if asked.

    Datasets come from the cache, which builds any that are missing.
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
    baseline = load_baseline(baseline_path)
    if update:
        save_baseline(baseline_path, build, measured, keep=baseline)
        baseline = load_baseline(baseline_path)
    findings = tuple(
        finding
        for (name, label), costs in measured.items()
        for finding in compare(OPERATIONS[name], label, costs, baseline.costs.get((name, label)))
    )
    events = {label: dataset.observations for label, dataset in gated.items()}
    scaled: list[Finding] = []
    expected: dict[str, Finding | None] = {}
    if SMALLEST in gated:
        for label in sorted(gated.keys() - {SMALLEST}):
            for name, operation in OPERATIONS.items():
                finding = scaling(
                    operation,
                    label,
                    (measured[(name, SMALLEST)], events[SMALLEST]),
                    (measured[(name, label)], events[label]),
                )
                if name in EXPECTED_SCALING_FAILURES:
                    expected[f"{name} on {label}"] = finding
                elif finding is not None:
                    scaled.append(finding)
    return GateReport(build, baseline.build, measured, events, findings, tuple(scaled), expected)


def _build(dataset: GateDataset) -> SqliteBuild:
    conn = open_cached(dataset.entry)
    try:
        return sqlite_build(conn)
    finally:
        conn.close()
