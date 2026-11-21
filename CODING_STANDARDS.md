# Code standards

Rules marked **[checked]** fail automatically in `tests/unit/test_standards.py`,
or in the test the rule names (`tests/unit/` runs in the pre-commit hook and CI's
`unit` job, `tests/data/` in CI's `data` job only). The
comment and docstring checks cover `computer_history/` and `tests/`; the rest
cover `computer_history/` only.
Unmarked rules are judgement calls the standards reviewer
(`.claude/agents/standards-reviewer.md`) enforces on each diff, citing each
rule by its ID.

## How rules are added

Review findings ratchet into rules:

1. A finding that is a repeatable pattern, not a one-off bug, becomes a new
   rule here with the next free ID in its section. A one-off bug gets a fix
   and a regression test instead.
2. A finding that cites an existing rule is its second sighting. If code can
   detect it, it becomes a test in `tests/unit/test_standards.py`, the rule is
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
- **S7** A type that summarises other values is named for what it counts
  (`CaptureCounts`), never as the plural of an item type in the same package.
- **S8** A value that picks behaviour is an Enum member, never a free string
  compared in branches (`FindingKind`, not `counter == "full scan"`).
- **S9** Setup and teardown that two modules repeat becomes one context manager
  beside the owner of the resource (`started` in `synthetic/operations.py`).
- **S10** A threshold constant is named for what it bounds
  (`VM_STEP_TOLERANCE`, `SLOWDOWN_TOLERANCE`), never as an adjective.
- **S11** A name joins a package's `__all__` only when code outside its
  module uses it (tests count); a helper only its own module calls stays
  `_private` (`_within` in `store/paths.py`). Ruff's RUF022 keeps every
  `__all__` sorted.
- **S12** A change to what a module handles updates its line in the package's
  flow diagram in the same commit.

## Architecture

- **A1** **[checked]** Layers depend downward only: `store/` never imports
  `sources/`, `synthetic/` or `cli/`; `sources/` never imports `synthetic/` or
  `cli/`; `synthetic/` never imports `cli/`.
- **A2** **[checked]** Only `store/` runs SQL.
- **A3** **[checked]** Only `cli/` opens connections and constructs clients;
  everything below takes them as parameters. `synthetic/` may also `connect`
  to a scratch database it builds, or `connect_immutable` to a cached one, by
  path, never the live one.
- **A4** Inject the I/O edges (`conn`, `client`, clock, sleep) and nothing else;
  pure logic takes plain data. Interfaces are Protocols (`AWApi`); transport
  clients stay dumb 1:1 API mirrors, with domain logic in free functions.
- **A5** Anything that must commit atomically lives in one function in one module.
- **A6** The top layer (CLI, later API/MCP) holds zero business logic: parse, call
  one function below, format, exit code. **[checked]** in part: no constant in
  `cli/` repeats one a lower layer defines with the same name and value.
- **A7** A path's resolution rule (flag, then `$ENV`, then default) lives in one
  function beside what owns the path (`resolve_db_path`, `cache_root`); other
  code calls it and never reads that variable itself.
- **A8** A module takes only the settings it reads: pass it the fields it
  uses, not a whole settings struct it reads part of.
- **A9** In-memory state keeps typed values; text from the spool or the wire
  is parsed once, where it comes in.
- **A10** A factory parameter that every production caller fills with a
  placeholder is removed, and the value is set once, where it becomes known.
- **A11** A Bool flag that picks between two counters becomes two methods.

## Hygiene

- **H1** A rename gets its own commit with minimal content changes, so git's
  rename detection keeps the file's history.
- **H2** Re-exports keep callers and tests untouched; tests monkeypatch the
  submodule that owns the name.
- **H3** **[checked]** `docs/DESIGN.md`'s package layout and any package README change in the
  same commit as the layout. The check covers the module names in the `store/`,
  `sources/` and `synthetic/` entries.
- **H4** Tests derive versions and counts from the code (`len(load_migrations())`),
  never hard-code them. They look things up by the constant that names them
  (`rendered[ActivityWatchRenderer.name]`, `ActivityWatchRenderer.streams`, the
  port in `DEFAULT_AW_URL`), never a restated literal; expected answers stay literals.
- **H5** A change to the pre-commit hook or CI updates every doc that describes
  the checks (`AGENTS.md`, `README.md`) in the same commit.
- **H6** **[checked]** Invisible and combining characters in source (Unicode
  categories Cf, Mn, Zl, Zp: bidi controls, zero-width marks, combining accents,
  line separators) are written as `\u` escapes, never raw.
- **H7** A capture-agent contract value the backend already defines (the
  heartbeat, the format version, the record kinds) is imported from `sources/`
  by `synthetic/`, never restated.
- **H8** **[checked]** in `tests/data/test_synthetic_coverage.py`: a new stream,
  table, timeline field or public store function on a connection lands with
  synthetic coverage in the same change (a renderer, generated rows, a
  rendered or manifest effect, a gate operation that runs it), or with an
  exemption in that test giving the reason.
- **H9** A change to a CLI command or flag updates `computer_history/cli/README.md`
  in the same commit.
- **H10** When a function already does something, call it rather than writing
  it again, and name a test after the code path it actually runs.
- **H11** Identifiers and docstrings use the GLOSSARY term, never a word in its
  _Avoid_ list; values already persisted are exempt.
- **H12** A change to a domain concept updates its glossary entry in the same
  change.
- **H13** **[checked]** in `tests/unit/test_standards.py`: `docs/agents/checks.md`
  names every CI and nightly job.
- **H14** A narrowing assert repeated on a store read in tests becomes one helper
  beside the test fixtures (`stored_progress` in `tests/db_states.py`).
- **H15** A constant a lower layer defines is imported, never restated under
  another name or value (`synthetic/` takes `DATABASE_NAME` from `store/`).
