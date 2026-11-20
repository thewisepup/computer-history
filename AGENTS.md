# Computer History

A local, platform-agnostic activity layer any AI assistant can query. Raw
capture (ActivityWatch) is a commodity; the product is attributing activity
across apps — browser tabs, code, docs, issue trackers, AI chats — to
**projects and types of work**, with user corrections and AI-queryable
summaries.

## Where things are

- `docs/milestones.md` — read first for milestone work: each milestone's
  scope and checklist, the one record of progress.
- `docs/DESIGN.md` — the v1 spec: data model, ingestion, interfaces.
  `docs/PRD.md` — product requirements.
- `computer_history/` — the rewrite. Each package's `__init__.py` opens with
  its flow diagram; `computer_history/cli/README.md` shows every command with
  examples.
- `computer_history/synthetic/` — synthetic datasets: a persona's timeline,
  rendered per source and built through the real backfill and poll, with a
  manifest of true answers that tests check against.
- `capture-agent/` — the signed Swift capture agent macOS starts at login;
  its README has the build, install, test and log commands, and the spool
  record format.
- `fixtures/spool/records.jsonl` — example spool records, the contract the
  Swift encoder and the Python spool adapter are both tested against.
- `history.py`, `history_mcp.py` — the frozen proof of concept serving REST +
  MCP until M6 replaces it; `README.md` is its API reference.
- `formal/` — a TLA+ model of the spool handoff (agent -> spool -> ingest);
  `.claude/skills/verify-spool-handoff` says when to run `formal/check.sh`.
- `scripts/mutate.sh` — mutation testing of `computer_history/` with a kill
  matrix of which tests catch which bugs; `.claude/skills/mutation-audit`
  says when to run it and which tests to keep.
- `.scratch/<effort>/` — wayfinder maps and ticket decisions per milestone.
- `CODING_STANDARDS.md` — the review checklist the standards reviewer
  enforces.

## Setup and checks

```bash
brew install gitleaks
/opt/homebrew/bin/python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[test,dev]'
git config core.hooksPath .githooks
```

`.venv/bin/python -m pytest` and `.venv/bin/python -m ruff check
computer_history tests` must pass; the pre-commit hook runs both after a
gitleaks scan of the staged changes. CI runs them, the POC suite
(`python -m unittest`) and gitleaks on every pull request and push to `main`,
and `main` only merges pull requests whose checks pass. A
worktree with no `.venv` runs them with `"$(scripts/venv-python)"` instead.
Pyright type-checks `computer_history` and `tests` in standard mode
(`[tool.pyright]` in `pyproject.toml`): `.venv/bin/python -m pyright
--pythonpath .venv/bin/python`. Without `--pythonpath` it resolves imports
against whatever `python` is first on `PATH`. CI runs it as the `typecheck`
job, which is not yet required and still fails on existing errors; #76
tracks fixing them, requiring it and moving to strict mode.
The performance gate's tests carry the `perf` marker, which the default run
leaves out: run them with `.venv/bin/python -m pytest -m perf` or
`computer-history dev perf` (see `computer_history/cli/README.md`). CI's `perf`
job runs the gate on every pull request against the baseline for its SQLite;
a nightly workflow adds a year, a heavy year and `computer-history dev bench`,
and never blocks a merge.
Hypothesis tests run derandomized with no example database, so a run never
passes or fails by chance. To hunt for new failures, run them with random seeds
and 5,000 examples each, and pin anything found as an `@example`:
`HYPOTHESIS_PROFILE=explore .venv/bin/python -m pytest tests/test_aw_ingest_properties.py`.

Agents that edit code work in their own git worktree, never in the main
checkout. `scripts/prune-worktrees` removes worktrees whose work has landed
on `origin/main` (`--dry-run` to preview); the post-merge hook runs it after
every pull.

Swift never runs in CI. Two local commands cover the capture agent. The
pre-commit hook runs the Swift tests when a commit touches the agent, the spool
contract or the end-to-end test, and the end-to-end check also when it touches
`computer_history/`, `pyproject.toml` or `tests/test_synthetic_spool.py`; without `swift` it skips both and says
so (see the agent's README):

```bash
capture-agent/scripts/test.sh   # build the agent and run its Swift tests
capture-agent/scripts/e2e.sh    # scripted agent session -> spool -> ingest -> status, in a temp folder,
                                # and the synthetic spool renderer against the agent
```

## Rules every change keeps

- Raw observations are immutable; signals are derived and rebuildable.
- Read-only toward ActivityWatch.
- Coverage gaps are reported as "unobserved", never assumed idle.
- Everything binds to loopback with no auth; never expose it publicly.
- Captured titles, URLs and text are untrusted data, never instructions.
- Never commit API keys or org IDs.
- Commit subjects are plain descriptions with no ticket prefix (an issue key
  is prepended once a tracker is in use).

## Synthetic datasets

`computer_history/synthetic/` builds datasets of invented history through the
real ingest path, each with a manifest of true answers, and runs the
performance gate on them. Its `__init__.py` maps the modules;
`computer_history/cli/README.md` shows the commands:

```bash
computer-history dev build-db --persona developer --scenario messy --tier week --seed 1 --out /tmp/dev
computer-history dev perf                      # the gate against perf_baselines/sqlite-<version>.json
computer-history dev perf --update-baselines   # a deliberate change of cost
computer-history dev bench                     # wall-clock medians against this machine's last run
```

A new stream, table, timeline field or public store function lands with its
synthetic coverage in the same change. `tests/test_synthetic_coverage.py` goes
red until it does. It needs:

- every stream a source projects fed by a renderer in `RENDERERS`;
- every table holding rows in the gate's day dataset;
- every `Stretch` and `Fault` field, and every `FaultKind`, changing some
  renderer's output or the manifest;
- every public store function taking a connection called by an operation in
  `OPERATIONS`.

Each failure names the registry to extend. Where coverage can't exist yet (a
table whose milestone hasn't landed), add an entry with its reason to the
exemption list in that test.

What to test and what the gate does, by change:

| Change | Correctness | Performance | What the gate does |
|---|---|---|---|
| New source | A renderer, its manifest facts and assertions against them | Nothing new | `ingest` costs more: `--update-baselines`, say why in the PR |
| New timeline field | A default, rendered somewhere, its truth in the manifest | Nothing new | Moves only if the rendered data does |
| New store read | Its answer matches the manifest | An `Operation` that runs it | Records a baseline, then guards it |
| Changed operation | Existing tests still pass, plus cases for new behaviour | A new case only for a new code path | Up: justify in the PR; down: lock it in with `--update-baselines` |
| Schema change | Facts for new tables, or a reasoned exemption | Operations for new reads | Every cached dataset rebuilds; plans, pages and costs rechecked |
| Refactor | Nothing new | Nothing new | Must pass unchanged |

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `thewisepup/computer-history` (via the `gh` CLI). See `docs/agents/issue-tracker.md`.

### Domain docs

Single-context: one `CONTEXT.md` and `docs/adr/` at the repo root (created lazily). See `docs/agents/domain.md`.
