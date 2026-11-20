"""Build the kill matrix: for each mutant the suite catches, every test that kills it.

Reruns each caught mutant against every test that calls the mutated function, without
stopping at the first failure, and writes mutants/matrix.json. An entry of null means
the rerun could not attribute the mutant.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mutants_data import MUTANTS, caught, load_exit_codes, load_stats, mutant_function

PLUGIN_DIR = Path(__file__).resolve().parent
TIMEOUT_SECONDS = 600


def killing_tests(mutant: str, tests: list[str]) -> list[str] | None:
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as out:
        failures = Path(out.name)
    env = {
        **{k: v for k, v in os.environ.items() if k != "MUTANT_UNDER_TEST"},
        "MUTATION_MUTANT": mutant,
        "MUTATION_FAILURES_FILE": str(failures),
        "PYTHONPATH": os.pathsep.join([str(MUTANTS), str(PLUGIN_DIR)]),
    }
    command = [
        sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
        "-p", "failures_plugin", "--no-header", "-o", "addopts=", *tests,
    ]
    try:
        run = subprocess.run(
            command, cwd=MUTANTS, env=env, capture_output=True, timeout=TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        return None
    finally:
        text = failures.read_text() if failures.exists() else ""
        failures.unlink(missing_ok=True)
    failed = [line for line in text.splitlines() if line]
    if run.returncode not in (0, 1) or not failed:
        print(f"\n{mutant}: pytest exit {run.returncode}, {len(failed)} failures", file=sys.stderr)
        return None
    return failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--out", type=Path, default=MUTANTS / "matrix.json")
    parser.add_argument(
        "--retry", action="store_true", help="rerun only mutants the last matrix left unattributed"
    )
    args = parser.parse_args()

    exit_codes = load_exit_codes(MUTANTS)
    tests_by_function = load_stats(MUTANTS)["tests_by_mangled_function_name"]
    killed = sorted(name for name, code in exit_codes.items() if caught(code))
    matrix: dict[str, list[str] | None] = {}
    if args.retry:
        matrix = json.loads(args.out.read_text())
        killed = [m for m in killed if not matrix.get(m)]

    def run(mutant: str) -> tuple[str, list[str] | None]:
        tests = sorted(tests_by_function.get(mutant_function(mutant), []))
        return mutant, killing_tests(mutant, tests)

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for done, (mutant, tests) in enumerate(pool.map(run, killed), start=1):
            matrix[mutant] = tests
            print(f"\r{done}/{len(killed)} mutants", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(matrix, indent=1, sort_keys=True) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
