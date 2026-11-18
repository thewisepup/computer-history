# Code standards

Every change is reviewed against these by the standards reviewer
(`.claude/agents/standards-reviewer.md`); ruff, pytest and the pre-commit
hook enforce what a tool can check.

## Comments: near-zero, never explanatory

- Default is no comment. Two exceptions: enumerating values
  (`source TEXT NOT NULL, -- 'aw-window' | 'aw-afk' | 'aw-web'`) and a single
  plain sentence for something a reader truly cannot see in the code.
- Never write reasoning-style comments — "X; because Y", "X: so that Z", or
  any clause justifying the code. Rationale belongs in commit messages and
  tickets.
- Docstrings say what the function does, in one or two plain-English
  sentences anyone can read. No references to DESIGN.md or other docs, no
  Sphinx/reST markup (`:func:`, double backticks), no contracts-and-caveats
  essays, no technical digressions.

## Structure: one module per concern

- Name modules for what they own (`observations.py`, `cursors.py`), never by
  operation direction (`reads.py`/`writes.py`) or as a grab-bag (`utils.py`,
  `shared.py`). Shared helpers get a focused, subject-named module (`text.py`,
  `formatting.py`).
- A file that accumulates multiple stages becomes a package: one module per
  stage plus an orchestrator (`activitywatch/ingest.py`, `cli/app.py`), with
  `__init__.py` carrying a short flow diagram and the public re-exports so
  callers do not change.
- Types live next to their producer (`BucketPull` beside `pull_bucket`),
  never in a `types.py`.
- A module never imports another module's `_private` names; make the name
  public where it lives instead.

## Architecture

- Inject the I/O edges as parameters — `conn`, `client`, `clock`, `sleep` —
  and nothing else; pure logic takes plain data. Interfaces are Protocols
  (`AWApi`); transport clients stay dumb 1:1 API mirrors; domain logic is
  free functions written against the interface, not methods on the client.
- Anything that must commit atomically lives in one function in one module.
- The top layer (CLI, later API/MCP) holds zero business logic: parse, call
  one function below, format, exit code.

## Hygiene on every change

- Refactors use `git mv` so history follows; re-exports keep callers and
  tests untouched; tests monkeypatch the submodule that owns the name.
- Docs track structure: `docs/DESIGN.md`'s package layout and any package
  README are updated in the same commit that changes the layout.
- Changing `project_signal` or `text.py` changes what a rebuild produces:
  run `rebuild-signals` and keep the ingest/rebuild identity test green.
- Tests derive versions and counts from the code (`len(load_migrations())`),
  never hard-code them.
