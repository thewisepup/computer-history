from __future__ import annotations

import argparse
import dataclasses
import sqlite3
import sys
import tempfile
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path

from computer_history.cli.formatting import copy_lines
from computer_history.store import (
    DB_ENV_VAR,
    DatabaseExists,
    DatabaseInUse,
    IntegrityCheckFailed,
    LiveDatabaseRefused,
    Profile,
    backup_database,
    default_db_path,
)
from computer_history.synthetic import (
    BASELINE,
    DATABASE_NAME,
    GATE_DATASETS,
    HEAVY,
    MANIFEST_NAME,
    OPERATIONS,
    PERF_DATASETS,
    PERSONAS,
    SCENARIOS,
    SMALLEST_DATASET,
    TIERS,
    UNEXPECTED_PASS_HINT,
    DatasetInputs,
    GateReport,
    OutputExists,
    OutputNotAFolder,
    cache_root,
    live_folders,
    make_dev_database,
    perf_datasets,
    run_gate,
)

LABELS = {DATABASE_NAME: "database", MANIFEST_NAME: "manifest"}
REFUSALS = (LiveDatabaseRefused, OutputExists, OutputNotAFolder)
FAILURES = (OSError, ValueError, LookupError, sqlite3.Error, RuntimeError)


def add_dev_commands(dev: argparse.ArgumentParser) -> None:
    commands = dev.add_subparsers(dest="dev_command", required=True)
    help_text = (
        "Build (or reuse from the dataset cache) a synthetic dataset and copy its database,"
        " manifest and rendered sources into a folder. Never touches the live database."
    )
    build = commands.add_parser("build-db", help=help_text, description=help_text)
    _add_dataset_inputs(build)
    build.add_argument("--out", type=Path, required=True, help="folder to copy the dataset into")
    build.add_argument(
        "--force", action="store_true", help="replace dataset files already in the folder"
    )
    help_text = (
        "Copy the live database into the dev folder's database, reading it without stopping or"
        " locking the stable backend. Copies neither the spool nor the screenshots."
    )
    snapshot = commands.add_parser("snapshot", help=help_text, description=help_text)
    snapshot.add_argument(
        "--db-path",
        default=argparse.SUPPRESS,
        help=f"database to copy into (default: ${DB_ENV_VAR}, else {DATABASE_NAME} in the dev"
        " folder); never one in the live folder",
    )
    snapshot.add_argument(
        "--force", action="store_true", help="replace the database already at that path"
    )
    help_text = (
        "Count the SQLite work of each operation on the gate's synthetic datasets and compare it"
        " with the committed baseline. Fails on any change past tolerance, cheaper ones too."
    )
    perf = commands.add_parser("perf", help=help_text, description=help_text)
    perf.add_argument(
        "--dataset",
        action="append",
        choices=list(PERF_DATASETS),
        help=f"dataset to measure, repeatable (default: {', '.join(GATE_DATASETS)})",
    )
    perf.add_argument(
        "--baseline",
        type=Path,
        default=BASELINE,
        help="baseline file, named sqlite-<version>.json for the SQLite it was counted on"
        f" (default: {BASELINE})",
    )
    perf.add_argument(
        "--update-baselines",
        action="store_true",
        help="record the measured costs in the baseline, then check against it; on another"
        " SQLite than the baseline's, its VM steps are kept",
    )
    perf.add_argument(
        "--counters",
        type=Path,
        help="also write the baseline file --update-baselines would write, to this path",
    )


def _add_dataset_inputs(build: argparse.ArgumentParser) -> None:
    for name, known in (("persona", PERSONAS), ("scenario", SCENARIOS), ("tier", TIERS)):
        build.add_argument(f"--{name}", choices=list(known), required=True, help=f"dataset {name}")
    build.add_argument("--seed", type=int, required=True, help="dataset seed")
    build.add_argument(
        "--start",
        type=date.fromisoformat,
        default=argparse.SUPPRESS,
        help=f"dataset start (default: {DatasetInputs.start})",
    )
    build.add_argument(
        "--timezone",
        default=argparse.SUPPRESS,
        help=f"dataset timezone (default: {DatasetInputs.timezone})",
    )
    build.add_argument(
        "--heavy",
        type=float,
        nargs="?",
        const=HEAVY,
        default=argparse.SUPPRESS,
        help=f"dataset heavy (default: {DatasetInputs.heavy}); --heavy alone means {HEAVY}",
    )


def cmd_dev(args: argparse.Namespace) -> int:
    return DEV_HANDLERS[args.dev_command](args)


def _failed(tool: str, exc: Exception) -> int:
    print(f"dev {tool} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1


def cmd_build_db(args: argparse.Namespace) -> int:
    names = [field.name for field in dataclasses.fields(DatasetInputs)]
    try:
        inputs = DatasetInputs(**{name: getattr(args, name) for name in names if name in args})
    except (ValueError, LookupError) as exc:
        print(f"dev build-db: invalid dataset inputs: {exc}", file=sys.stderr)
        return 2
    try:
        made = make_dev_database(
            inputs,
            args.out,
            cache=cache_root(),
            live=live_folders(args.db_path, args.profile),
            force=args.force,
        )
    except REFUSALS as exc:
        print(f"dev build-db refused: {exc}", file=sys.stderr)
        return 1
    except FAILURES as exc:
        return _failed("build-db", exc)
    described = ", ".join(f"{name}={value}" for name, value in dataclasses.asdict(inputs).items())
    how = "built" if made.dataset.built else "reused from the cache"
    print(f"Dataset {described}")
    print(f"  {how}: {made.dataset.folder}")
    for path in made.copied:
        label = LABELS.get(path.name, path.name + ("/" if path.is_dir() else ""))
        print(f"  {label:<10} {path}")
    return 0


def cmd_snapshot(args: argparse.Namespace) -> int:
    live = default_db_path(Profile.STABLE)
    try:
        copy = backup_database(live, args.database, replace=args.force)
    except DatabaseExists as exc:
        print(f"dev snapshot refused: {exc}; pass --force to replace it", file=sys.stderr)
        return 1
    except DatabaseInUse as exc:
        print(f"dev snapshot refused: {exc}", file=sys.stderr)
        return 1
    except (FileNotFoundError, IntegrityCheckFailed) as exc:
        print(f"dev snapshot failed: {exc}", file=sys.stderr)
        return 1
    except FAILURES as exc:
        return _failed("snapshot", exc)
    print(f"Snapshot of the live database {live}")
    for line in copy_lines(copy):
        print(line)
    return 0


def cmd_perf(args: argparse.Namespace) -> int:
    datasets = perf_datasets(args.dataset)
    with tempfile.TemporaryDirectory(prefix="computer-history-perf-") as scratch:
        try:
            report = run_gate(
                datasets,
                cache=cache_root(),
                scratch=Path(scratch),
                baseline=args.baseline,
                update=args.update_baselines,
                counters=args.counters,
            )
        except FAILURES as exc:
            return _failed("perf", exc)
    _print_report(report, args)
    return 0 if report.ok else 1


def _print_report(report: GateReport, args: argparse.Namespace) -> None:
    build = report.build
    print(f"SQLite {build.version}, {len(build.compile_options)} compile options:")
    print(f"  {' '.join(build.compile_options)}")
    print(f"Baseline: {report.baseline}")
    if not report.compares_vm_steps:
        print(
            f"  SQLite {build.version} is not the baseline's {report.baseline_sqlite}: compared"
            " statements, full scans and pages but not VM steps, which CI's perf job checks"
        )
    if args.update_baselines:
        kept = "" if report.compares_vm_steps else ", keeping its VM steps"
        print(f"Baseline rewritten from this run{kept}.")
    if args.counters is not None:
        print(f"Counters written: {args.counters}, the file --update-baselines would write")
    print()
    print(f"{'operation':<16} {'dataset':<11} {'statements':>11} {'VM steps':>13} {'pages':>8}")
    for (name, label), costs in report.measured.items():
        pages = f"{costs.pages:,}" if OPERATIONS[name].writes else "-"
        print(f"{name:<16} {label:<11} {costs.statements:>11,} {costs.vm_steps:>13,} {pages:>8}")
    if not report.scaling_checked:
        print(f"scaling not checked: it needs {SMALLEST_DATASET} and a larger dataset")
    for finding in report.expected.values():
        if finding is not None:
            print(f"expected to fail, {finding.describe().splitlines()[0]}")
    print()
    if report.ok:
        print("Performance gate passed.")
        return
    for finding in report.failures:
        print(finding.describe())
    for name, label in report.unexpected_passes:
        print(f"{name} on {label}: the scaling check passes now; {UNEXPECTED_PASS_HINT}")
    count = len(report.failures) + len(report.unexpected_passes)
    print(f"Performance gate failed: {count} findings.")


DEV_HANDLERS: Mapping[str, Callable[[argparse.Namespace], int]] = {
    "build-db": cmd_build_db,
    "snapshot": cmd_snapshot,
    "perf": cmd_perf,
}
