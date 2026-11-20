# Where each check runs

Every check runs at exactly one of four stages. Put a new check at the
earliest stage it fits; move it later when it outgrows that stage.

| Stage | Runs | Budget | Holds |
|---|---|---|---|
| Pre-commit hook (`.githooks/pre-commit`) | on every commit, on your machine | about 15 s in total; no test over 3 s | gitleaks on the staged changes, ruff, pytest without the `perf` and `dataset` markers |
| Pull request CI (`.github/workflows/ci.yml`) | on every pull request and push to `main` | about 20 min per job | the full pytest, the POC suite, gitleaks on the history, pyright, the performance gate, and on macOS (`agent`) the Swift tests and a release build of the app bundle, signed ad hoc |
| Nightly (`.github/workflows/nightly.yml`) | once a day, and on demand | hours | year datasets, wall-clock benchmarks, and the end-to-end check through the real agent (`agent-e2e`) |

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

CI's `check` job sets `COMPUTER_HISTORY_HOOK_BUDGET=1`, and `tests/conftest.py`
then fails the run when a test the hook runs takes over 3 s (setup and call),
or all of them together over 15 s. It names each slow test. Either make it
faster, or give its file `pytestmark = pytest.mark.dataset` so it runs in CI
alone.
