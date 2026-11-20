# Code standards

Rules marked **[checked]** fail automatically in `tests/test_standards.py`
(run by the pre-commit hook and CI). The comment and docstring checks cover
`computer_history/` and `tests/`; the rest cover `computer_history/` only.
Unmarked rules are judgement calls the standards reviewer
(`.claude/agents/standards-reviewer.md`) enforces on each diff, citing each
rule by its ID.

## How rules are added

Review findings ratchet into rules:

1. A finding that is a repeatable pattern, not a one-off bug, becomes a new
   rule here with the next free ID in its section. A one-off bug gets a fix
   and a regression test instead.
2. A finding that cites an existing rule is its second sighting. If code can
   detect it, it becomes a test in `tests/test_standards.py`, the rule is
   marked **[checked]**, and the reviewer stops looking for it. If only
   judgement can detect it, it stays a reviewer rule.

## Comments: near-zero, never explanatory

- **C1** **[checked]** Comments are single plain lines: no multi-line blocks, no
  reasoning clauses (`;`, "because", "so that", "to avoid").
- **C2** Default is no comment. The exceptions: enumerating values
  (`source TEXT NOT NULL, -- 'aw-window' | 'aw-afk' | 'aw-web'`) and one
  plain sentence for something a reader truly cannot see in the code.
  Rationale belongs in commit messages and tickets.
- **C3** **[checked]** Function and class docstrings are at most two sentences.
- **C4** **[checked]** Docstrings carry no doc references (DESIGN.md, `§`, ticket
  numbers) and no Sphinx/reST markup (`:func:`, double backticks, `::`).
- **C5** Docstrings say what the code does in plain English anyone can read: no
  contracts-and-caveats detail, no technical digressions.

## Structure: one module per concern

- **S1** **[checked]** No grab-bag module names: `utils`, `helpers`, `misc`,
  `common`, `shared`, `types`, `reads`, `writes`.
- **S2** Name modules for what they own (`observations.py`, `cursors.py`); shared
  helpers get a focused, subject-named module (`text.py`, `formatting.py`).
- **S3** A file that accumulates multiple stages becomes a package: one module per
  stage plus an orchestrator (`activitywatch/ingest.py`, `cli/app.py`), with
  `__init__.py` carrying a short flow diagram and the public re-exports.
- **S4** **[checked]** A package diagram names every module in the package, and only
  modules that exist.
- **S5** Types live next to their producer (`BucketPull` beside `pull_bucket`).
- **S6** **[checked]** No module imports another module's `_private` names.

## Architecture

- **A1** **[checked]** Layers depend downward only: `store/` never imports
  `sources/` or `cli/`; `sources/` never imports `cli/`.
- **A2** **[checked]** Only `store/` runs SQL.
- **A3** **[checked]** Only `cli/` opens connections and constructs clients;
  everything below takes them as parameters.
- **A4** Inject the I/O edges (`conn`, `client`, clock, sleep) and nothing else;
  pure logic takes plain data. Interfaces are Protocols (`AWApi`); transport
  clients stay dumb 1:1 API mirrors, with domain logic in free functions.
- **A5** Anything that must commit atomically lives in one function in one module.
- **A6** The top layer (CLI, later API/MCP) holds zero business logic: parse, call
  one function below, format, exit code.

## Hygiene

- **H1** A rename gets its own commit with minimal content changes, so git's
  rename detection keeps the file's history.
- **H2** Re-exports keep callers and tests untouched; tests monkeypatch the
  submodule that owns the name.
- **H3** `docs/DESIGN.md`'s package layout and any package README change in the
  same commit as the layout.
- **H4** Tests derive versions and counts from the code (`len(load_migrations())`),
  never hard-code them.
- **H5** A change to the pre-commit hook or CI updates every doc that describes
  the checks (`AGENTS.md`, `README.md`) in the same commit.
