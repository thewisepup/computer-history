# 01 — Package skeleton + tooling

Type: task
Status: resolved

## Task

Create the `computer_history/` package (M1 subset of the §2 layout:
`store/`, `sources/`, `cli.py`) and wire up tooling, without touching the
POC's behavior.

- `computer_history/` package at repo root with `store/` and `sources/`
  subpackages and `cli.py` (argparse or similar; `computer-history` console
  script in `pyproject.toml`).
- `pyproject.toml` updated: package discovery covering both the POC modules
  and the new package, pytest + ruff as dev deps, ruff config, pytest config
  (`tests/` directory for the new package's tests).
- One smoke test (imports the package, runs a trivial CLI invocation) passes
  via `.venv/bin/python -m pytest`.
- POC still works: `.venv/bin/python -m unittest` still passes and
  `history.py serve` still starts.

## Acceptance

`pytest` green, `unittest` green, `computer-history --help` prints the
command list.

## Answer

Done (Opus 5.5 implementer + medium code review, 2026-11-17).

- `computer_history/` package: `__init__.py`, `store/`, `sources/`, `cli.py`
  (argparse; four stub subcommands exiting 1; global `--db-path`).
- `pyproject.toml`: distribution renamed `computer-history-poc` →
  `computer-history` (stale venvs need `pip uninstall computer-history-poc`);
  console script `computer-history = computer_history.cli:main`; pytest +
  ruff in dev extra; pytest collects only `tests/`; ruff excludes the frozen
  POC files (34 pre-existing findings).
- `tests/test_cli.py`: 6 tests, STUB_COMMANDS derived from `cli.COMMANDS`.
- Review fixes applied: dropped opaque `metavar="COMMAND"`, derived test
  command list, AGENTS.md "rewrite in progress" note + git-repo correction.
- Verified: pytest 6 passed, POC unittest 12 passed, ruff clean,
  `history.py serve` still healthy.
- Note for ticket 02: `--db-path` help already documents the
  `$COMPUTER_HISTORY_DB` fallback and the Application Support default —
  implement resolution exactly as documented.
