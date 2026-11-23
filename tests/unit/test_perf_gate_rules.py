from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

from computer_history.synthetic import (
    BASELINE,
    OPERATIONS,
    Costs,
    FindingKind,
    GateDataset,
    Operation,
    Scan,
    StatementCost,
    baseline_sqlite,
    compare,
    load_baseline,
    measure_operation,
    save_baseline,
    scaling,
    with_vm_steps_of,
    without_vm_steps,
)
from computer_history.synthetic.operations import Session

INSERT = "INSERT INTO observations (source) VALUES (?)"
PROGRESS = "SELECT position FROM ingest_progress WHERE source = ?"
COUNT = 'SELECT COUNT(*) FROM "observations"'
GAPS = "SELECT started_at, ended_at FROM observations WHERE source = ? AND started_at < ?"


def _costs(
    statements: dict[str, tuple[int, int]],
    *,
    scans: tuple[Scan, ...] = (),
    pages: int = 100,
    table_pages: dict[str, int] | None = None,
) -> Costs:
    by_statement = {text: StatementCost(*cost) for text, cost in statements.items()}
    return Costs(
        statements=sum(cost.runs for cost in by_statement.values()),
        vm_steps=sum(cost.vm_steps for cost in by_statement.values()),
        full_scans=scans,
        pages=pages,
        table_pages={"observations": 60} if table_pages is None else table_pages,
        by_statement=by_statement,
    )


BASE = _costs({INSERT: (100, 10_000), PROGRESS: (10, 1_000)})


def test_matching_costs_pass() -> None:
    assert compare(OPERATIONS["ingest"], "day", BASE, BASE) == []


def test_one_more_statement_fails_and_names_the_statement_that_grew() -> None:
    worse = _costs({INSERT: (100, 10_000), PROGRESS: (11, 1_000)})

    [finding] = compare(OPERATIONS["ingest"], "day", worse, BASE)

    assert (finding.counter, finding.before, finding.after, finding.cheaper) == (
        "statements",
        110,
        111,
        False,
    )
    assert finding.grew == (f"10 -> 11 runs, 1,000 -> 1,000 VM steps: {PROGRESS}",)
    assert "ingest on day: statements 110 -> 111 (+0.9%)" in finding.describe()


def test_vm_steps_pass_within_two_percent_and_fail_beyond_it_either_way() -> None:
    def steps(insert_steps: int) -> Costs:
        return _costs({INSERT: (100, insert_steps), PROGRESS: (10, 1_000)})

    ingest = OPERATIONS["ingest"]
    assert compare(ingest, "day", steps(10_219), BASE) == []
    assert compare(ingest, "day", steps(9_781), BASE) == []
    [worse] = compare(ingest, "day", steps(10_221), BASE)
    [cheaper] = compare(ingest, "day", steps(9_779), BASE)

    assert (worse.counter, worse.before, worse.after, worse.cheaper) == (
        "vm_steps",
        11_000,
        11_221,
        False,
    )
    assert (cheaper.counter, cheaper.after, cheaper.cheaper) == ("vm_steps", 10_779, True)
    assert "--update-baselines" in cheaper.describe()


def test_pages_are_exact_for_an_operation_that_writes_and_ignored_for_reads() -> None:
    bigger = _costs(
        {INSERT: (100, 10_000), PROGRESS: (10, 1_000)},
        pages=101,
        table_pages={"observations": 61},
    )

    found = compare(OPERATIONS["ingest"], "day", bigger, BASE)

    assert [(f.counter, f.before, f.after) for f in found] == [
        ("pages", 100, 101),
        ("pages of observations", 60, 61),
    ]
    assert compare(OPERATIONS["status-reads"], "day", bigger, BASE) == []


def test_a_scan_off_the_allowlist_fails_even_when_the_baseline_has_it() -> None:
    scan = Scan("observations", GAPS)
    scanning = _costs({GAPS: (1, 500)}, scans=(scan,))

    [finding] = compare(OPERATIONS["status-reads"], "day", scanning, scanning)

    assert finding.kind is FindingKind.SCAN_NOT_ALLOWED
    assert "observations" in finding.describe() and GAPS in finding.describe()


def test_an_allowlisted_scan_passes_but_a_new_one_asks_for_a_baseline_update() -> None:
    counting = _costs({COUNT: (1, 9)}, scans=(Scan("observations", COUNT),))
    not_counting = _costs({COUNT: (1, 9)})

    assert compare(OPERATIONS["status-reads"], "day", counting, counting) == []
    [finding] = compare(OPERATIONS["status-reads"], "day", counting, not_counting)
    assert (finding.kind, finding.cheaper) == (FindingKind.SCANS_CHANGED, False)
    assert "new observations in SELECT COUNT(*)" in finding.describe()


def test_a_missing_baseline_asks_for_one() -> None:
    [finding] = compare(OPERATIONS["ingest"], "month", BASE, None)

    assert finding.kind is FindingKind.NO_BASELINE
    assert "--update-baselines" in finding.describe()


def test_a_windowed_read_may_grow_to_twice_its_day_cost_leaving_out_allowlisted_scans() -> None:
    day = _costs({GAPS: (3, 1_000), COUNT: (1, 50)})
    twice = _costs({GAPS: (3, 2_000), COUNT: (1, 5_000)})
    more = _costs({GAPS: (3, 2_001), COUNT: (1, 50)})
    reads = OPERATIONS["status-reads"]

    assert scaling(reads, "month", (day, 100), (twice, 3_000)) is None
    finding = scaling(reads, "month", (day, 100), (more, 3_000))
    assert finding is not None
    assert (finding.kind, finding.before, finding.after) == (FindingKind.SCALING, 2_000, 2_001)


def test_an_operation_over_all_data_may_grow_half_again_faster_than_its_events() -> None:
    day = _costs({INSERT: (100, 1_000)})
    in_step = _costs({INSERT: (3_000, 45_000)})
    faster = _costs({INSERT: (3_000, 45_001)})
    ingest = OPERATIONS["ingest"]

    assert scaling(ingest, "month", (day, 100), (in_step, 3_000)) is None
    finding = scaling(ingest, "month", (day, 100), (faster, 3_000))
    assert finding is not None
    assert (finding.before, finding.after) == (45_000, 45_001)


def test_a_baseline_round_trips_through_its_file(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    scanning = _costs({COUNT: (1, 9)}, scans=(Scan("observations", COUNT),))

    save_baseline(path, {("ingest", "day"): BASE, ("status-reads", "day"): scanning})

    assert load_baseline(path) == {
        ("ingest", "day"): BASE,
        ("status-reads", "day"): _costs(
            {COUNT: (1, 9)}, scans=(Scan("observations", COUNT),), pages=0, table_pages={}
        ),
    }


def test_updating_some_entries_keeps_the_others(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    save_baseline(path, {("ingest", "day"): BASE, ("ingest", "month"): BASE})
    cheaper = _costs({INSERT: (100, 9_000), PROGRESS: (10, 1_000)})

    save_baseline(path, {("ingest", "day"): cheaper}, keep=load_baseline(path))

    assert load_baseline(path) == {("ingest", "day"): cheaper, ("ingest", "month"): BASE}


def test_updating_drops_entries_of_operations_that_are_gone(tmp_path: Path) -> None:
    path = tmp_path / "baseline.json"
    stale = {("ingest", "day"): BASE, ("status", "day"): BASE}

    save_baseline(path, {("ingest", "day"): BASE}, keep=stale)

    assert list(load_baseline(path)) == [("ingest", "day")]


def test_the_baseline_names_the_sqlite_its_costs_were_counted_on() -> None:
    assert baseline_sqlite(Path("perf_baselines/sqlite-3.45.1.json")) == "3.45.1"
    assert [path.name for path in BASELINE.parent.iterdir()] == [BASELINE.name]


def test_without_vm_steps_costs_that_differ_only_in_vm_steps_compare_equal() -> None:
    other_sqlite = _costs({INSERT: (100, 13_000), PROGRESS: (10, 900)})
    one_more = _costs({INSERT: (100, 13_000), PROGRESS: (11, 900)})
    ingest = OPERATIONS["ingest"]

    assert compare(ingest, "day", without_vm_steps(other_sqlite), without_vm_steps(BASE)) == []
    [finding] = compare(ingest, "day", without_vm_steps(one_more), without_vm_steps(BASE))
    assert (finding.counter, finding.before, finding.after) == ("statements", 110, 111)


def test_an_update_on_another_sqlite_keeps_the_baselines_vm_steps() -> None:
    measured = _costs({INSERT: (101, 13_000), GAPS: (1, 500)})

    kept = with_vm_steps_of(measured, BASE)

    assert (kept.statements, kept.vm_steps) == (102, BASE.vm_steps)
    assert kept.by_statement == {INSERT: (101, 10_000), GAPS: (1, 500)}
    assert with_vm_steps_of(measured, None) == measured


def _scratch_operation(fresh: bool, seen: list[list[str]]) -> Operation:
    def start(dataset: GateDataset, folder: Path) -> Session:
        folder.mkdir(parents=True)
        seen.append(sorted(path.name for path in folder.parent.iterdir() if path != folder))
        (folder / "copy.db").write_bytes(b"x" * 1024)
        return Session(sqlite3.connect(":memory:"), lambda: None)

    return Operation("scratch", start, fresh=fresh)


def test_an_operation_leaves_no_scratch_and_keeps_one_copy_at_a_time(tmp_path: Path) -> None:
    seen: list[list[str]] = []
    dataset = cast(GateDataset, None)

    measure_operation(_scratch_operation(True, seen), dataset, tmp_path / "fresh")
    measure_operation(_scratch_operation(False, seen), dataset, tmp_path / "reused")

    assert seen == [[], []]
    assert list(tmp_path.iterdir()) == []
