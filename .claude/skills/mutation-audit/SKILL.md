---
name: mutation-audit
description: Mutation-test computer_history/ with mutmut, build a kill matrix of which tests catch which mutants, and decide which tests to keep, prune or add. Use when asked whether a test earns its keep, to prune or consolidate tests, after a large change to store, sources or cli code, or when asked for a mutation score.
---

# Mutation audit

A mutant is a small deliberate bug (`>` to `>=`, a string to `"XX…XX"`, a
return value to `None`). A test **kills** a mutant when it fails against it.
The audit proves each kept test catches some bug no other kept test catches.

## Run

```bash
scripts/mutate.sh                        # whole package, about an hour
scripts/mutate.sh computer_history.store # one module's mutants only
```

It installs mutmut (the `mutation` extra) when the venv lacks it, removes the
`setproctitle` it pulls in (see AGENTS.md), deletes `mutants/`, runs
`mutmut run`, then:

1. `scripts/mutation/matrix.py` reruns every killed mutant against every test
   that calls the mutated function, without stopping at the first failure,
   and writes `mutants/matrix.json` (mutant to killing tests). mutmut alone
   stops at the first kill, so it cannot show redundancy.
2. `scripts/mutation/report.py report` writes `mutants/report.md`: the score,
   each test's verdict by file, and each surviving mutant with its diff.

`mutants/` is gitignored. `mutmut show <mutant>` prints one mutant's diff;
`mutmut browse` explores results.

## Scope

- Mutated: `computer_history/` only. Not the POC (`history.py`,
  `history_mcp.py`), not Swift (issue #48).
- Not run against mutants, and never pruned, because they check things the
  tool cannot see: `tests/unit/test_standards.py`, `tests/unit/test_spool_fixture.py`,
  `tests/e2e/test_capture_e2e.py`, `tests/data/test_synthetic_cli_http.py` (both run
  the CLI as a subprocess, which mutmut cannot follow) and
  `tests/data/test_synthetic_coverage.py` (it traces store functions by name, which
  mutmut's wrappers hide). The list is
  `pytest_add_cli_args_test_selection` in `pyproject.toml`.
- mutmut mutates Python only, never the SQL in `store/migrations/`. A test
  that guards a rule the schema enforces (a trigger, `UNIQUE`, a foreign key,
  a data migration) is marked `@pytest.mark.schema_rule` and never pruned.
- `cli/` mutants that only `XX`-wrap a string containing a space (a message)
  are excluded from the score and the survivor list. Rewording a message is
  not a bug; a broken format string or command name is.

## Which tests stay

1. **Required:** the only test that kills some mutant. Keep.
2. **Cover:** after the required tests, the report greedily adds the test
   that kills the most still-unkilled mutants per function it calls, until
   every caught mutant is covered. A focused test beats a broad CLI or
   backfill test that fails on any bug in `connect()`. Keep.
3. **Protected:** marked `schema_rule`, or calls a mutant the rerun could not
   attribute to any test. Keep.
4. **Prune:** one or two kept tests kill all its mutants. Delete it, or merge
   it into a parametrized sibling. This holds for a redundant test that
   guards an AGENTS.md rule too: one test per rule is enough.
5. **Prune (scattered):** its mutants are killed only by three or more kept
   tests together, so no single test covers its scenario. Read each one in
   the module PR: prune it, or keep it and say why in the PR.

Prune only from a full run. A module run leaves other mutants unchecked, and
the report says so at the top.

Merging near-duplicates into one `pytest.mark.parametrize` test is allowed and
preferred over deleting them one by one. Rename kept tests so each name states
the behavior it pins.

## Surviving mutants

Triage `store/`, `sources/capture_spool/`, `sources/commit.py` and
`sources/activitywatch/` first. Each survivor gets one outcome:

- **Add a test** through the module's public functions only. Never import or
  call a private name to reach a mutant.
- **Delete the code** when no public behavior can reach the mutant: it is
  dead or defensive code that does nothing.
- **Mark it equivalent** with `# pragma: no mutate` and one plain line in the
  PR saying why the mutant cannot change behavior.

## Prove a pruning change

Before deleting tests, keep the full-run matrix:

```bash
cp mutants/matrix.json /tmp/before.json
# prune, merge, add tests, delete code
scripts/mutate.sh
"$(scripts/venv-python)" scripts/mutation/report.py compare /tmp/before.json mutants/matrix.json
```

`compare` exits 1 and lists every mutant that was killed before and is not
now. Each one must be a mutant whose code the change deleted. mutmut numbers
mutants within a function, so editing a function renumbers its mutants and
they all show up here: check those functions' survivors in the new report by
hand. A change that only touches tests keeps every name. The PR carries:
the score before and after, each pruned test with the kept tests that still
kill its mutants, and each survivor with its outcome.
