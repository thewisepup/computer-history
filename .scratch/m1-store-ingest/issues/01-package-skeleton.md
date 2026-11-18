# 01 — Package skeleton + tooling

Type: task
Status: open

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
