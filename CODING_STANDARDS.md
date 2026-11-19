# Code standards

Rules marked **[checked]** fail automatically in `tests/test_standards.py`
(run by the pre-commit hook and CI). The comment and docstring checks cover
`computer_history/` and `tests/`; the rest cover `computer_history/` only. The rest are judgement calls the
standards reviewer (`.claude/agents/standards-reviewer.md`) enforces on each
diff.

## Comments: near-zero, never explanatory

- **[checked]** Comments are single plain lines: no multi-line blocks, no
  reasoning clauses (`;`, "because", "so that", "to avoid").
- Default is no comment. The exceptions: enumerating values
  (`source TEXT NOT NULL, -- 'aw-window' | 'aw-afk' | 'aw-web'`) and one
  plain sentence for something a reader truly cannot see in the code.
  Rationale belongs in commit messages and tickets.
- **[checked]** Function and class docstrings are at most two sentences.
- **[checked]** Docstrings carry no doc references (DESIGN.md, `§`, ticket
  numbers) and no Sphinx/reST markup (`:func:`, double backticks, `::`).
- Docstrings say what the code does in plain English anyone can read: no
  contracts-and-caveats detail, no technical digressions.

## Structure: one module per concern

- **[checked]** No grab-bag module names: `utils`, `helpers`, `misc`,
  `common`, `shared`, `types`, `reads`, `writes`.
- Name modules for what they own (`observations.py`, `cursors.py`); shared
  helpers get a focused, subject-named module (`text.py`, `formatting.py`).
- A file that accumulates multiple stages becomes a package: one module per
  stage plus an orchestrator (`activitywatch/ingest.py`, `cli/app.py`), with
  `__init__.py` carrying a short flow diagram and the public re-exports.
- **[checked]** A package diagram names every module in the package, and only
  modules that exist.
- Types live next to their producer (`BucketPull` beside `pull_bucket`).
- **[checked]** No module imports another module's `_private` names.

## Architecture

- **[checked]** Layers depend downward only: `store/` never imports
  `sources/` or `cli/`; `sources/` never imports `cli/`.
- **[checked]** Only `store/` runs SQL.
- **[checked]** Only `cli/` opens connections and constructs clients;
  everything below takes them as parameters.
- Inject the I/O edges (`conn`, `client`, clock, sleep) and nothing else;
  pure logic takes plain data. Interfaces are Protocols (`AWApi`); transport
  clients stay dumb 1:1 API mirrors, with domain logic in free functions.
- Anything that must commit atomically lives in one function in one module.
- The top layer (CLI, later API/MCP) holds zero business logic: parse, call
  one function below, format, exit code.

## Hygiene

- A rename gets its own commit with minimal content changes, so git's
  rename detection keeps the file's history.
- Re-exports keep callers and tests untouched; tests monkeypatch the
  submodule that owns the name.
- `docs/DESIGN.md`'s package layout and any package README change in the
  same commit as the layout.
- Tests derive versions and counts from the code (`len(load_migrations())`),
  never hard-code them.
