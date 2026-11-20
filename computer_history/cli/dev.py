from __future__ import annotations

import argparse
import dataclasses
import sqlite3
import sys
import tempfile
import typing
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

from computer_history.synthetic import (
    BASELINE_DIR,
    BENCH_BASELINE_NAME,
    DATABASE_NAME,
    GATE_DATASETS,
    MANIFEST_NAME,
    OPERATIONS,
    PERF_DATASETS,
    PERSONAS,
    RUNS,
    SCENARIOS,
    SLOWDOWN_TOLERANCE,
    SMALLEST,
    TIERS,
    BuildFailed,
    DatasetInputs,
    GateReport,
    Timing,
    cache_root,
    live_folders,
    make_dev_database,
    perf_datasets,
    run_bench,
    run_gate,
)

REGISTRIES: Mapping[str, Mapping[str, object]] = {
    "persona": PERSONAS,
    "scenario": SCENARIOS,
    "tier": TIERS,
}
PARSERS: Mapping[type, Callable[[str], Any]] = {
    str: str,
    int: int,
    float: float,
    date: date.fromisoformat,
}
LABELS = {DATABASE_NAME: "database", MANIFEST_NAME: "manifest"}


def add_dev_commands(dev: argparse.ArgumentParser) -> None:
    commands = dev.add_subparsers(dest="dev_command", required=True)
    help_text = (
        "Build (or reuse from the dataset cache) a synthetic dataset and copy its database,"
        " manifest and rendered sources into a folder. Never touches the live database."
    )
    build = commands.add_parser("build-db", help=help_text, description=help_text)
    hints = typing.get_type_hints(DatasetInputs)
    for field in dataclasses.fields(DatasetInputs):
        _add_input_option(build, field, hints[field.name])
    build.add_argument("--out", type=Path, required=True, help="folder to copy the dataset into")
    build.add_argument(
        "--force", action="store_true", help="replace dataset files already in the folder"
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
        "--baselines",
        type=Path,
        default=BASELINE_DIR,
        help=f"folder of baseline files, one per SQLite version (default: {BASELINE_DIR})",
    )
    perf.add_argument(
        "--update-baselines",
        action="store_true",
        help="record the measured costs as this SQLite's baseline, then check against it",
    )
    perf.add_argument(
        "--counters",
        type=Path,
        help="also write the baseline file --update-baselines would write, to this path",
    )
    help_text = (
        f"Time each operation {RUNS} times on synthetic datasets and compare the median with this"
        f" machine's last baseline, flagging any over {SLOWDOWN_TOLERANCE:.0%} slower. Never fails."
    )
    bench = commands.add_parser("bench", help=help_text, description=help_text)
    bench.add_argument(
        "--dataset",
        action="append",
        choices=list(PERF_DATASETS),
        help=f"dataset to time, repeatable (default: {', '.join(GATE_DATASETS)})",
    )
    bench.add_argument(
        "--baseline",
        type=Path,
        help=f"this machine's timings (default: {BENCH_BASELINE_NAME} in the dataset cache)",
    )
    bench.add_argument(
        "--update-baseline",
        action="store_true",
        help="record these timings as the machine's new baseline",
    )


def _add_input_option(
    parser: argparse.ArgumentParser, field: dataclasses.Field[Any], kind: object
) -> None:
    flag = "--" + field.name.replace("_", "-")
    required = field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING
    default = argparse.SUPPRESS if not required else None
    shown = "" if required else f" (default: {field.default})"
    if kind is bool:
        parser.add_argument(flag, dest=field.name, action="store_true", default=default)
        return
    if kind not in PARSERS:
        raise TypeError(f"dev build-db cannot parse DatasetInputs.{field.name} ({kind})")
    choices = REGISTRIES.get(field.name)
    parser.add_argument(
        flag,
        dest=field.name,
        type=PARSERS[kind],
        choices=None if choices is None else list(choices),
        required=required,
        default=default,
        help=f"dataset {field.name.replace('_', ' ')}{shown}",
    )


def cmd_dev(args: argparse.Namespace) -> int:
    return DEV_HANDLERS[args.dev_command](args)


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
            live=live_folders(args.db_path),
            force=args.force,
        )
    except (ValueError, OSError, BuildFailed) as exc:
        print(f"dev build-db refused: {exc}", file=sys.stderr)
        return 1
    described = ", ".join(f"{name}={value}" for name, value in dataclasses.asdict(inputs).items())
    how = "built" if made.dataset.built else "reused from the cache"
    print(f"Dataset {described}")
    print(f"  {how}: {made.dataset.folder}")
    for path in made.copied:
        label = LABELS.get(path.name, path.name + ("/" if path.is_dir() else ""))
        print(f"  {label:<10} {path}")
    return 0


def cmd_perf(args: argparse.Namespace) -> int:
    datasets = perf_datasets(args.dataset)
    with tempfile.TemporaryDirectory(prefix="computer-history-perf-") as scratch:
        try:
            report = run_gate(
                datasets,
                cache=cache_root(),
                scratch=Path(scratch),
                baselines=args.baselines,
                update=args.update_baselines,
                counters=args.counters,
            )
        except (OSError, ValueError, LookupError, sqlite3.Error, RuntimeError) as exc:
            print(f"dev perf failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    _print_report(report, args)
    return 0 if report.ok else 1


def _print_report(report: GateReport, args: argparse.Namespace) -> None:
    build = report.build
    print(f"SQLite {build.version}, {len(build.compile_options)} compile options:")
    print(f"  {' '.join(build.compile_options)}")
    older = sorted(
        {version for key, version in report.recorded_on.items() if key in report.measured}
        - {build.version}
    )
    print(f"Baseline: {report.baseline}")
    if older:
        print(
            f"  note: entries recorded on SQLite {', '.join(older)}, whose VM steps can differ;"
            f" --update-baselines records SQLite {build.version}'s own"
        )
    if args.update_baselines:
        print("Baseline rewritten from this run.")
    if args.counters is not None:
        print(
            f"Counters written: {args.counters},"
            f" the {report.own_baseline.name} --update-baselines would write"
        )
    print()
    print(f"{'operation':<16} {'dataset':<11} {'statements':>11} {'VM steps':>13} {'pages':>8}")
    for (name, label), costs in report.measured.items():
        pages = f"{costs.pages:,}" if OPERATIONS[name].writes else "-"
        print(f"{name:<16} {label:<11} {costs.statements:>11,} {costs.vm_steps:>13,} {pages:>8}")
    if not report.scaling_checked:
        print(f"scaling not checked: it needs {SMALLEST} and a larger dataset")
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
        print(
            f"{name} on {label}: the scaling check passes now;"
            " take it off EXPECTED_SCALING_FAILURES"
        )
    count = len(report.failures) + len(report.unexpected_passes)
    print(f"Performance gate failed: {count} findings.")


def cmd_bench(args: argparse.Namespace) -> int:
    with tempfile.TemporaryDirectory(prefix="computer-history-bench-") as scratch:
        try:
            report = run_bench(
                perf_datasets(args.dataset),
                cache=cache_root(),
                scratch=Path(scratch),
                baseline_path=args.baseline,
                update=args.update_baseline,
            )
        except (OSError, ValueError, LookupError, sqlite3.Error, RuntimeError) as exc:
            print(f"dev bench failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    print(f"Median of {RUNS} runs, against this machine's baseline {report.baseline}")
    print()
    print(f"{'operation':<16} {'dataset':<11} {'median':>10} {'baseline':>10} {'change':>9}")
    for timing in report.timings:
        print(_timing_row(timing))
    print()
    slower = sum(timing.slower for timing in report.timings)
    tolerance = f"{SLOWDOWN_TOLERANCE:.0%}"
    if slower:
        noun = "timing" if slower == 1 else "timings"
        print(
            f"{slower} {noun} more than {tolerance} slower than this machine's baseline."
            " A report, not a failure: rerun with --update-baseline once the cost is intended."
        )
    else:
        print(f"Nothing more than {tolerance} slower than this machine's baseline.")
    return 0


def _timing_row(timing: Timing) -> str:
    known = timing.baseline
    baseline = "-" if known is None else f"{known:.3f} s"
    change = "recorded" if timing.change is None else f"{timing.change:+.1%}"
    row = (
        f"{timing.operation:<16} {timing.dataset:<11} {timing.median:>8.3f} s"
        f" {baseline:>10} {change:>9}"
    )
    return f"{row}  SLOWER" if timing.slower else row


DEV_HANDLERS: Mapping[str, Callable[[argparse.Namespace], int]] = {
    "build-db": cmd_build_db,
    "perf": cmd_perf,
    "bench": cmd_bench,
}
