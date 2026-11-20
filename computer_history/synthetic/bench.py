"""The wall-clock benchmark: each operation's median time against this machine's last baseline."""

from __future__ import annotations

import json
import shutil
import statistics
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from computer_history.synthetic.cache import cached_dataset
from computer_history.synthetic.generate import DatasetInputs
from computer_history.synthetic.operations import (
    OPERATIONS,
    GateDataset,
    Operation,
    gate_dataset,
)

RUNS = 5
SLOWER = 0.25
BENCH_BASELINE_NAME = "bench_baseline.json"


@dataclass(frozen=True)
class Timing:
    """An operation's median seconds on a dataset, and this machine's baseline for it, if any."""

    operation: str
    dataset: str
    median: float
    baseline: float | None

    @property
    def change(self) -> float | None:
        return None if self.baseline is None else self.median / self.baseline - 1

    @property
    def slower(self) -> bool:
        return self.change is not None and self.change > SLOWER


def bench_baseline_path(cache: Path) -> Path:
    """Where this machine keeps its benchmark baseline: beside its cached datasets."""
    return cache / BENCH_BASELINE_NAME


def time_operation(
    operation: Operation,
    dataset: GateDataset,
    folder: Path,
    *,
    clock: Callable[[], float] = time.perf_counter,
) -> tuple[float, ...]:
    """The seconds each of five runs takes, each started afresh in scratch that is then removed."""
    times = []
    for run in range(RUNS):
        scratch = folder / str(run)
        try:
            session = operation.start(dataset, scratch)
            try:
                began = clock()
                session.action()
                times.append(clock() - began)
            finally:
                session.conn.close()
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    shutil.rmtree(folder, ignore_errors=True)
    return tuple(times)


def run_bench(
    datasets: Mapping[str, DatasetInputs],
    *,
    cache: Path,
    scratch: Path,
    baseline_path: Path,
    update: bool = False,
) -> tuple[Timing, ...]:
    """Time every operation on every dataset and compare each median with the baseline.

    Timings the baseline lacks are recorded into it, and every timing when updating.
    """
    baseline = _load(baseline_path)
    timings = []
    for label, inputs in datasets.items():
        dataset = gate_dataset(inputs, cached_dataset(inputs, cache))
        for name, operation in OPERATIONS.items():
            median = statistics.median(time_operation(operation, dataset, scratch / label / name))
            known = None if update else baseline.get(name, {}).get(label)
            timings.append(Timing(name, label, median, known))
            if known is None:
                baseline.setdefault(name, {})[label] = median
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(json.dumps(baseline, indent=1, sort_keys=True) + "\n", "utf-8")
    return tuple(timings)


def _load(path: Path) -> dict[str, dict[str, float]]:
    if not path.exists():
        return {}
    data: dict[str, dict[str, float]] = json.loads(path.read_text(encoding="utf-8"))
    return data
