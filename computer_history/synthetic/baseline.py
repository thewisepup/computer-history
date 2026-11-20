"""The committed baselines: each operation's costs per dataset, one file per SQLite version."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from computer_history.synthetic.meter import Costs, Scan, StatementCost
from computer_history.synthetic.operations import OPERATIONS, Operation

BASELINE_DIR = Path(__file__).with_name("perf_baselines")

Key = tuple[str, str]


@dataclass(frozen=True)
class Baseline:
    """Recorded costs and SQLite versions, by operation and dataset."""

    costs: Mapping[Key, Costs]
    versions: Mapping[Key, str]


def baseline_file(version: str, folder: Path = BASELINE_DIR) -> Path:
    """The baseline file for costs counted on one SQLite version."""
    return folder / f"sqlite-{version}.json"


def compared_baseline(version: str, folder: Path = BASELINE_DIR) -> Path:
    """The SQLite version's own baseline file, else the newest version's, else its own unwritten."""
    own = baseline_file(version, folder)
    others = {
        _version(path): path
        for path in folder.glob(baseline_file("*", folder).name)
        if _version(path) is not None
    }
    if own.exists() or not others:
        return own
    return others[max(others)]


def _version(path: Path) -> tuple[int, ...] | None:
    parts = path.stem.removeprefix("sqlite-").split(".")
    return tuple(int(part) for part in parts) if all(part.isdigit() for part in parts) else None


def recorded(operation: Operation, costs: Costs) -> Costs:
    """The costs the gate keeps for the operation: pages only for one that writes."""
    return costs if operation.writes else replace(costs, pages=0, table_pages={})


def load_baseline(path: Path) -> Baseline:
    """The baseline in the file, or an empty one if there is no file."""
    if not path.exists():
        return Baseline({}, {})
    data = json.loads(path.read_text(encoding="utf-8"))
    costs: dict[Key, Costs] = {}
    versions: dict[Key, str] = {}
    for operation, datasets in data.items():
        for dataset, entry in datasets.items():
            versions[(operation, dataset)] = entry["sqlite_version"]
            costs[(operation, dataset)] = Costs(
                statements=entry["statements"],
                vm_steps=entry["vm_steps"],
                full_scans=tuple(Scan(*scan) for scan in entry["full_scans"]),
                pages=entry["pages"],
                table_pages=entry["table_pages"],
                by_statement={
                    text: StatementCost(*cost) for text, cost in entry["by_statement"].items()
                },
            )
    return Baseline(costs, versions)


def save_baseline(
    path: Path, version: str, costs: Mapping[Key, Costs], keep: Baseline | None = None
) -> None:
    """Write the costs, recorded on the SQLite version, over the kept baseline's other entries.

    Entries for operations that no longer exist are dropped.
    """
    merged = {key: (cost, version) for key, cost in costs.items()}
    if keep is not None:
        for key, cost in keep.costs.items():
            merged.setdefault(key, (cost, keep.versions[key]))
    data: dict[str, dict[str, object]] = {}
    for (name, dataset), (measured, recorded_on) in sorted(merged.items()):
        if name not in OPERATIONS:
            continue
        entry = recorded(OPERATIONS[name], measured)
        data.setdefault(name, {})[dataset] = {
            "sqlite_version": recorded_on,
            "statements": entry.statements,
            "vm_steps": entry.vm_steps,
            "full_scans": sorted(list(scan) for scan in entry.full_scans),
            "pages": entry.pages,
            "table_pages": dict(sorted(entry.table_pages.items())),
            "by_statement": {text: list(cost) for text, cost in sorted(entry.by_statement.items())},
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
