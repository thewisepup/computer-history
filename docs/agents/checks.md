# Where each check runs

Every check runs at one of three stages. Put a new check at the
earliest stage it fits; move it later when it outgrows that stage.

| Stage | Runs | Budget | Holds |
|---|---|---|---|
| Pre-commit hook (`.githooks/pre-commit`) | on every commit, on your machine | seconds; nothing enforces it. A slow unit test is made faster; a test that builds a dataset goes in `tests/data/` | gitleaks on the staged changes, ruff check and format, `pytest -n auto tests/unit`, pyright |
| Pull request CI (`.github/workflows/ci.yml`) | on every pull request and push to `main` | about 20 min per job | `lint`: ruff check and ruff format --check. `unit`: `pytest -n auto tests/unit`, with its temporary files on tmpfs (`/dev/shm`). `data`: `pytest -n auto --dist worksteal tests/data`, one pytest-xdist worker per core. `poc`: the POC suite (`python -m unittest`). `secrets`: gitleaks on the history. `typecheck`: pyright (`computer_history` strict, `tests` standard). `perf`: the performance gate on day and month datasets, its scratch on tmpfs. `changes`: decides which of the others a pull request's diff reaches (see below). `macos-capture-agent-tests`: the Swift tests and a release build of the app bundle, signed ad hoc. `macos-capture-agent-e2e`: the end-to-end check through the real agent |
| Nightly (`.github/workflows/nightly.yml`) | once a day, and on demand | hours | `perf`: the gate on year and heavy-year datasets, and wall-clock benchmarks. |

`main` requires `lint`, `unit`, `data`, `poc`, `secrets`, `macos-capture-agent-tests` and `macos-capture-agent-e2e` to pass before a merge.
`typecheck` is required on pull requests too; the release gate leaves it out.
Push to `main` reruns pull request CI; there is no separate main-only stage.

## Skipping what a pull request can't reach

On a pull request, the `changes` job feeds the diff's paths to
`scripts/ci-changes`, and each job runs only if some path can reach it.
Every push to `main` runs every job, so the release gate always sees a full
run, and a wrong skip shows up on `main` before `install` or `update` takes
that commit.

| Jobs | Skipped when every changed path is |
|---|---|
| `lint`, `unit`, `data`, `poc`, `typecheck`, `perf` | Markdown, an image or `.scratch/`, except the docs a test reads (`READ_BY_TESTS`: `docs/DESIGN.md`, `docs/agents/checks.md`) |
| `macos-capture-agent-e2e` | Markdown, an image or `.scratch/` (test-read docs included), or off the agent -> spool -> ingest -> signals -> status path (`OFF_THE_E2E_PATH`: CLI commands the e2e never runs, `tests/unit/`, most of `tests/data/`, the POC, `.claude/`, `formal/`, ...). `stable/`, `host/` and `watchdog/` stay on it: the e2e is the one run of the real host adapter |
| `macos-capture-agent-tests` | outside `capture-agent/` and `fixtures/spool/`, and neither `ci.yml` nor `scripts/ci-changes` |

`secrets` always runs. A skipped job counts as passed for the merge rule.
The lists name what is known not to matter, so a new path runs everything
until someone adds it. A diff that can't be read, or a `changes` job that
fails, runs everything too. `tests/unit/test_ci_changes.py` pins the rules and
fails when a test starts naming a Markdown file the first rule would skip.
The Python jobs install with uv (`astral-sh/setup-uv`, no cache: a cold
install takes about 3s). Every test HTTP server is a `LoopbackHTTPServer` from
`tests/aw_http.py`: the standard library's `HTTPServer` names itself with
`socket.getfqdn`, which takes 35s on the macOS runner.
Installing the agent (`install.sh`) needs a login session and your signing
certificate, so it stays a step you run by hand.

## Merge conflicts

`.github/workflows/fix-conflicts.yml` is not a check and never blocks a
merge. On every push, its `find` job lists the open pull requests based on the
pushed branch that now conflict. It takes only Brandon's own pull requests,
skips forks and the `no-autofix` label, and starts one dispatched run per
pull request. That run's `fix` job has
Claude Code merge the base in: Sonnet at medium effort, then Opus at high
effort if the first try fails. It pushes a merge commit only after ruff and
`tests/unit` pass, and never force-pushes. Then it comments on the pull
request. A real disagreement gets a "needs you" comment, no push, and the
`no-autofix` label, so later pushes skip it.

- It runs on Brandon's subscription (the `CLAUDE_CODE_OAUTH_TOKEN` secret)
  through the Claude GitHub App.
- The Claude action only runs the copy of the workflow on `main`, so a change
  to this file can only be tested after it merges.
- `gh workflow run fix-conflicts.yml -f pr=<number>` runs it by hand, label or
  not; on a pull request without conflicts it does nothing.

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
