# Where each check runs

Every check runs at one of three stages. Put a new check at the
earliest stage it fits; move it later when it outgrows that stage.

| Stage | Runs | Budget | Holds |
|---|---|---|---|
| Pre-commit hook (`.githooks/pre-commit`) | on every commit, on your machine | seconds; nothing enforces it. A slow unit test is made faster; a test that builds a dataset goes in `tests/data/` | gitleaks on the staged changes, ruff check and format, `pytest -n 4 tests/unit`, pyright. Beside it, `.githooks/commit-msg` refuses a ticket or milestone prefix on the subject |
| Pull request CI (`.github/workflows/ci.yml`) | on every pull request and push to `main` | about 20 min per job | `lint`: ruff check and ruff format --check. `unit`: `pytest -n auto tests/unit`, with its temporary files on tmpfs (`/dev/shm`). `data`: `pytest -n auto --dist worksteal tests/data`, one pytest-xdist worker per core. `poc`: the POC suite (`python -m unittest`). `secrets`: gitleaks on the history. `typecheck`: pyright (`computer_history` strict, `tests` standard). `perf`: the performance gate on day and month datasets, its scratch on tmpfs. `macos-capture-agent-tests`: the Swift tests and a release build of the app bundle, signed ad hoc, on every push to `main` and on pull requests whose diff touches `capture-agent/`, `fixtures/spool/` or `ci.yml` (the job's `REACHES`); otherwise it passes with a "Skipped" notice, and it runs everything when the diff can't be read. `macos-capture-agent-e2e`: the end-to-end check through the real agent |
| Nightly (`.github/workflows/nightly.yml`) | once a day, and on demand | hours | `perf`: the gate on year and heavy-year datasets, and wall-clock benchmarks. |

`main` requires `lint`, `unit`, `data`, `poc`, `secrets`, `macos-capture-agent-tests` and `macos-capture-agent-e2e` to pass before a merge.
`typecheck` is required on pull requests too; the release gate leaves it out.
Push to `main` reruns pull request CI; there is no separate main-only stage.
The Python jobs install with uv (`astral-sh/setup-uv`, no cache: a cold
install takes about 3s).
Installing the agent (`install.sh`) needs a login session and your signing
certificate, so it stays a step you run by hand.

## Merge conflicts

`.github/workflows/fix-conflicts.yml` is not a check and never blocks a
merge. On every push, its `find` job lists the open pull requests based on the
pushed branch that now conflict. It takes only Brandon's own pull requests,
skips forks and the `no-autofix` label, and starts one dispatched run per
pull request. Code Claude writes never runs on a runner that holds a
secret, and only `land` pushes:

- `sonnet` has Claude Code resolve the conflicts at medium effort. Claude
  gets Read, Edit, Write, Glob and Grep and no shell, so nothing it writes
  runs there. Both sides of each conflict and their history are laid out as
  files for it. Its job token is read-only. The job uploads the files Claude
  changed.
- `check-sonnet` holds no secret. It applies those files to the merge, runs
  ruff and `tests/unit`, commits the merge and bundles it.
- If that fails, `opus` and `check-opus` do the same at high effort, with
  the first attempt's report or failing check as notes.
- `land` runs no AI and none of the repository's code. On a fresh runner
  it checks the bundle again: a merge of the branch's current tip and the
  base, no conflict markers, no secrets, and no new content under
  `.github/`, `.githooks/` or `.claude/`. Then it
  turns off auto-merge, pushes with the Claude GitHub App's token (a plain
  push, never forced, so CI starts) and comments that the merge needs your
  review before you merge.

A real disagreement, or any failed check, gets a "needs you" comment, no
push, and the `no-autofix` label, so later pushes skip it. Claude's notes in
that comment are redacted, cut to 40 lines and put in a code block.

- It runs on Brandon's subscription (the `CLAUDE_CODE_OAUTH_TOKEN` secret)
  through the Claude GitHub App.
- Every action in the three workflows is pinned to a commit SHA, with its
  tag in a trailing comment.
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
