"""The committed baseline: each operation's costs per dataset, counted on CI's SQLite."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from computer_history.synthetic.meter import Costs, Scan, StatementCost
from computer_history.synthetic.operations import OPERATIONS, Operation

BASELINE = Path(__file__).with_name("perf_baselines") / "sqlite-3.45.1.json"

Key = tuple[str, str]


def baseline_sqlite(path: Path) -> str:
    """The SQLite version the baseline file's costs were counted on, from its name."""
    return path.stem.removeprefix("sqlite-")


def recorded(operation: Operation, costs: Costs) -> Costs:
    """The costs the gate keeps for the operation: pages only for one that writes."""
    return costs if operation.writes else replace(costs, pages=0, table_pages={})


def without_vm_steps(costs: Costs) -> Costs:
    """The costs any SQLite version counts the same: all but VM steps."""
    return replace(
        costs,
        vm_steps=0,
        by_statement={
            text: StatementCost(cost.runs, 0) for text, cost in costs.by_statement.items()
        },
    )


def with_vm_steps_of(costs: Costs, kept: Costs | None) -> Costs:
    """The costs with the kept entry's VM steps, wherever it has them."""
    if kept is None:
        return costs
    return replace(
        costs,
        vm_steps=kept.vm_steps,
        by_statement={
            text: StatementCost(cost.runs, kept.by_statement.get(text, cost).vm_steps)
            for text, cost in costs.by_statement.items()
        },
    )


def load_baseline(path: Path) -> dict[Key, Costs]:
    """The costs in the file, or none if there is no file."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
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
        for operation, datasets in data.items()
        for dataset, entry in datasets.items()
    }


def save_baseline(
    path: Path, costs: Mapping[Key, Costs], keep: Mapping[Key, Costs] | None = None
) -> None:
    """Write the costs over the kept baseline's other entries.

    Entries for operations that no longer exist are dropped.
    """
    merged = {**(keep or {}), **costs}
    data: dict[str, dict[str, object]] = {}
    for (name, dataset), measured in sorted(merged.items()):
        if name not in OPERATIONS:
            continue
        entry = recorded(OPERATIONS[name], measured)
        data.setdefault(name, {})[dataset] = {
            "statements": entry.statements,
            "vm_steps": entry.vm_steps,
            "full_scans": sorted(list(scan) for scan in entry.full_scans),
            "pages": entry.pages,
            "table_pages": dict(sorted(entry.table_pages.items())),
            "by_statement": {text: list(cost) for text, cost in sorted(entry.by_statement.items())},
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
