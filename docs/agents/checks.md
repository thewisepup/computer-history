# Where each check runs

Every check runs at one of three stages. Put a new check at the
earliest stage it fits; move it later when it outgrows that stage.

| Stage | Runs | Budget | Holds |
|---|---|---|---|
| Pre-commit hook (`.githooks/pre-commit`) | on every commit, on your machine | seconds; nothing enforces it. A slow unit test is made faster; a test that builds a dataset goes in `tests/data/` | gitleaks on the staged changes, ruff check and format, `pytest tests/unit`, pyright |
| Pull request CI (`.github/workflows/ci.yml`) | on every pull request and push to `main` | about 20 min per job | `lint`: ruff check and ruff format --check. `unit`: `pytest tests/unit`. `data`: `pytest tests/data`. `poc`: the POC suite (`python -m unittest`). `secrets`: gitleaks on the history. `typecheck`: pyright (`computer_history` strict, `tests` standard), not yet required. `perf`: the performance gate on day and month datasets. `macos-capture-agent-tests`: the Swift tests and a release build of the app bundle, signed ad hoc, on every push to `main` and on pull requests whose diff touches `capture-agent/`, `fixtures/spool/` or `ci.yml` (the job's `REACHES`); otherwise it passes with a "Skipped" notice, and it runs everything when the diff can't be read. `macos-capture-agent-e2e`: the end-to-end check through the real agent |
| Nightly (`.github/workflows/nightly.yml`) | once a day, and on demand | hours | `perf`: the gate on year and heavy-year datasets, and wall-clock benchmarks. |

`main` requires `lint`, `unit`, `data`, `poc`, `secrets`, `macos-capture-agent-tests` and `macos-capture-agent-e2e` to pass before a merge.
Push to `main` reruns pull request CI; there is no separate main-only stage.
Installing the agent (`install.sh`) needs a login session and your signing
certificate, so it stays a step you run by hand.

## Choosing a stage

- **Pre-commit** holds checks that are fast, deterministic and local: no
  network, no Swift build, no dataset builds. It catches what would otherwise
  be pushed broken.
- **Pull request CI** holds everything that must pass before a merge and fits
  its budget. A check here is a merge gate, so it must give the same answer on
  every run.
- **Nightly** holds what is too slow for a pull request, measures wall-clock
  time, or needs a platform build that rarely changes. It reports and never
  blocks a merge.
