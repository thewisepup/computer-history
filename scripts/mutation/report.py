"""Turn the kill matrix into a keep/prune report, or compare two matrices.

report: picks the smallest set of tests that still kills every caught mutant and
writes markdown listing kept tests, prune candidates and surviving mutants.
compare: lists mutants a before-matrix holds that an after-matrix no longer holds.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from mutants_data import (
    MUTANTS,
    load_exit_codes,
    load_stats,
    mutant_diff,
    mutant_function,
    mutant_module,
    only_changes_a_message,
    status,
)


def choose_tests(
    kills: dict[str, set[str]], focus: dict[str, int]
) -> tuple[set[str], set[str]]:
    """Return (required, cover): sole killers of some mutant, then a greedy cover of the rest."""
    killers: dict[str, set[str]] = defaultdict(set)
    for test, mutants in kills.items():
        for mutant in mutants:
            killers[mutant].add(test)
    required = {next(iter(tests)) for tests in killers.values() if len(tests) == 1}
    uncovered = set(killers) - set().union(*(kills[t] for t in required))
    cover: set[str] = set()
    while uncovered:
        best = max(
            (t for t in kills if t not in required | cover),
            key=lambda t: (len(kills[t] & uncovered), -focus.get(t, 0), t),
        )
        cover.add(best)
        uncovered -= kills[best]
    return required, cover


def replacements(test: str, kills: dict[str, set[str]], kept: set[str]) -> list[str]:
    remaining = set(kills[test])
    chosen = []
    while remaining:
        best = max(sorted(kept), key=lambda t: len(kills.get(t, set()) & remaining))
        chosen.append(best)
        remaining -= kills.get(best, set())
    return chosen


def short(test: str) -> str:
    return test.split("::", 1)[1]


def report(module: str | None) -> str:
    exit_codes = load_exit_codes(MUTANTS)
    stats = load_stats(MUTANTS)
    matrix: dict[str, list[str] | None] = json.loads((MUTANTS / "matrix.json").read_text())

    all_tests = set(stats["duration_by_test"])
    focus = Counter(t for tests in stats["tests_by_mangled_function_name"].values() for t in tests)
    kills: dict[str, set[str]] = {t: set() for t in all_tests}
    killers: dict[str, set[str]] = defaultdict(set)
    tests_by_function = stats["tests_by_mangled_function_name"]
    unattributed = sorted(m for m, tests in matrix.items() if not tests)
    protected = {t for m in unattributed for t in tests_by_function.get(mutant_function(m), [])}
    for mutant, tests in matrix.items():
        for test in tests or []:
            kills.setdefault(test, set()).add(mutant)
            killers[mutant].add(test)
    partial = any(status(c) == "not checked" for c in exit_codes.values())
    if module:
        exit_codes = {m: c for m, c in exit_codes.items() if m.startswith(module)}
    required, cover = choose_tests(kills, focus)
    protected -= required | cover
    kept = required | cover | protected
    prune = sorted(set(kills) - kept)

    checked = {m: c for m, c in exit_codes.items() if status(c) != "not checked"}
    by_status = Counter(status(c) for c in checked.values())
    survivors = sorted(m for m, c in checked.items() if status(c) in {"survived", "no tests"})
    cli_strings = [
        m for m in survivors
        if ".cli." in m and only_changes_a_message(mutant_diff(MUTANTS, m))
    ]
    real_survivors = [m for m in survivors if m not in cli_strings]
    scored = len(checked) - len(cli_strings)
    score = 100 * by_status["killed"] / scored if scored else 0.0

    out = [f"# Mutation report{f' for {module}' if module else ''}", ""]
    if partial:
        out += [
            "> **Partial run.** Some mutants were not checked, so a test marked prune may "
            "still be the only killer of an unchecked mutant. Prune only from a full run.",
            "",
        ]
    out += [
        "| | count |", "|---|---|",
        f"| mutants checked | {len(checked)} |",
        *(f"| {s} | {n} |" for s, n in sorted(by_status.items())),
        f"| cli message-only survivors (not scored) | {len(cli_strings)} |",
        f"| **score** (killed / checked, excluding cli messages) | **{score:.1f}%** |",
        "",
        "| tests | count |", "|---|---|",
        f"| required (only killer of some mutant) | {len(required)} |",
        f"| cover (needed to kill the rest) | {len(cover)} |",
        f"| protected (call a mutant the rerun could not attribute) | {len(protected)} |",
        f"| prune candidates | {len(prune)} |",
        "",
    ]
    if unattributed:
        out += [
            "Caught mutants the rerun could not attribute to a test. Every test calling "
            "their function is kept:",
            *(f"- `{m}`" for m in unattributed), "",
        ]

    out += ["## Tests by file", ""]
    by_file: dict[str, list[str]] = defaultdict(list)
    for test in kills:
        by_file[test.split("::", 1)[0]].append(test)
    for path in sorted(by_file):
        tests = sorted(by_file[path])
        out += [f"### {path}", "", "| test | verdict | unique kills | kills | still killed by |",
                "|---|---|---|---|---|"]
        for test in tests:
            unique = sum(1 for m in kills[test] if killers[m] == {test})
            if test in required:
                verdict, by = "keep (required)", ""
            elif test in cover:
                verdict, by = "keep (cover)", ""
            elif test in protected:
                verdict, by = "keep (protected)", ""
            else:
                verdict = "prune" if kills[test] else "prune (kills nothing)"
                by = ", ".join(f"`{short(t)}`" for t in replacements(test, kills, kept))
            out.append(f"| `{short(test)}` | {verdict} | {unique} | {len(kills[test])} | {by} |")
        out.append("")

    out += ["## Surviving mutants", ""]
    by_source: dict[str, list[str]] = defaultdict(list)
    for mutant in real_survivors:
        by_source[mutant_module(mutant)].append(mutant)
    for source in sorted(by_source):
        out += [f"### {source}", "", "| mutant | status | change |", "|---|---|---|"]
        for mutant in by_source[source]:
            change = "; ".join(f"`{o}` → `{n}`" for o, n in mutant_diff(MUTANTS, mutant))
            out.append(
                f"| `{mutant.rsplit('.', 1)[1]}` | {status(checked[mutant])} "
                f"| {change.replace('|', chr(92) + '|')} |"
            )
        out.append("")
    return "\n".join(out)


def compare(before: Path, after: Path) -> int:
    old = set(json.loads(before.read_text()))
    new = set(json.loads(after.read_text()))
    lost = sorted(old - new)
    print(f"caught before: {len(old)}  after: {len(new)}  no longer caught: {len(lost)}")
    for mutant in lost:
        print(f"  {mutant}")
    return 1 if lost else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    rep = sub.add_parser("report")
    rep.add_argument(
        "--module",
        help="mutant name prefix; narrows the score and survivors, never the choice of tests",
    )
    rep.add_argument("--out", type=Path, default=MUTANTS / "report.md")
    cmp = sub.add_parser("compare")
    cmp.add_argument("before", type=Path)
    cmp.add_argument("after", type=Path)
    args = parser.parse_args()
    if args.command == "compare":
        sys.exit(compare(args.before, args.after))
    args.out.write_text(report(args.module) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
