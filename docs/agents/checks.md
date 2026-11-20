# Where each check runs

Every check runs at one of three stages. Put a new check at the
earliest stage it fits; move it later when it outgrows that stage.

| Stage | Runs | Budget | Holds |
|---|---|---|---|
| Pre-commit hook (`.githooks/pre-commit`) | on every commit, on your machine | about 15 s in total; no test over 3 s | gitleaks on the staged changes, ruff, pytest without the `perf` and `dataset` markers, pyright |
| Pull request CI (`.github/workflows/ci.yml`) | on every pull request and push to `main` | about 20 min per job | `check`: ruff, the full pytest with the hook's budget, the POC suite. `secrets`: gitleaks on the history. `typecheck`: pyright (`computer_history` strict, `tests` standard), not yet required. `perf`: the performance gate on day and month datasets. `macos-capture-agent-tests`: the Swift tests and a release build of the app bundle, signed ad hoc. `macos-capture-agent-e2e`: the end-to-end check through the real agent |
| Nightly (`.github/workflows/nightly.yml`) | once a day, and on demand | hours | `perf`: the gate on year and heavy-year datasets, and wall-clock benchmarks. |

`main` requires `check`, `secrets`, `macos-capture-agent-tests` and `macos-capture-agent-e2e` to pass before a merge.
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

## The hook's budget

The value of `COMPUTER_HISTORY_HOOK_BUDGET` is how much slower than a laptop
the machine runs. CI's `check` job sets `2`, since its runners take about twice
as long. `tests/conftest.py` then fails the run when a test the hook runs takes
over 3 s times that factor (setup and call), or all of them together over
15 s times it, and names each slow test. Either make it faster, or give its
file `pytestmark = pytest.mark.dataset` so only CI runs it. Run it locally with
`COMPUTER_HISTORY_HOOK_BUDGET=1 .venv/bin/python -m pytest -m "not perf and not dataset"`.
