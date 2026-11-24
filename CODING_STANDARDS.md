# Code standards

Rules marked **[checked]** fail automatically in `tests/unit/test_standards.py`,
or in the test the rule names; each failure names the offending lines. The
checks cover `computer_history/`, and the comment, docstring and
invisible-character checks cover `tests/` too. A rule marked **[checked]** in
part keeps a judgement half the reviewer still checks.
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
- **S5** Types live next to their producer (`SourcePull` beside `pull_source`).
- **S6** **[checked]** No module imports another module's `_private` names.
- **S7** A type that summarises other values is named for what it counts
  (`CaptureCounts`), never as the plural of an item type in the same package.
- **S8** A value that picks behaviour is an Enum member, never a free string
  compared in branches (`FindingKind`, not `counter == "full scan"`).
- **S9** Setup and teardown that two modules repeat becomes one context manager
  beside the owner of the resource (`started` in `synthetic/operations.py`).
- **S10** A threshold constant is named for what it bounds
  (`VM_STEP_TOLERANCE`, `WINDOWED_GROWTH`), never as an adjective.
- **S11** A name joins a package's `__all__` only when code outside its
  module uses it (tests count); a helper only its own module calls stays
  `_private` (`_within` in `store/paths.py`).
- **S12** A change to what a module handles updates its line in the package's
  flow diagram in the same commit.

## Architecture

- **A1** **[checked]** Layers depend downward only, as
  `FORBIDDEN_IMPORTS` in `tests/unit/test_standards.py` lists per package
  (`host/` imports none, `cli/` may import all).
- **A2** **[checked]** Only `store/` runs SQL.
- **A3** **[checked]** Only `cli/` opens connections and constructs clients
  (the host adapter's `LiveHost` among them); everything below takes them as
  parameters. `synthetic/` may also `connect`
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
- **A10** Folded into A14.
- **A11** A Bool flag that picks between two counters becomes two methods.
- **A12** A command's failures reach the CLI as one domain exception the layer
  below raises (`InstallFailed`, `BackupFailed`, `RestoreFailed`), carrying
  the message to print; the CLI never catches a tuple of library exceptions
  (`OSError`, `sqlite3.Error`) itself.
- **A13** A file or link rewritten in place (a state file, a pointer, the PATH
  link) goes through the one atomic-write helper, `replace_atomically` in
  `store/paths.py`, never its own staged write and `os.replace`.
- **A14** No parameter, Protocol or option without a second real caller: a
  value only one caller ever passes is fixed where it is used, and a factory
  parameter every production caller fills with a placeholder is removed and
  set once, where it becomes known. A test alone is not a second caller. The
  exceptions are the I/O edges A4 injects and a deliberate seam that makes a
  test deterministic (a clock, a chunk or batch size).

## Logging

- **L1** One summary record per unit of work (a watch cycle, a backfill run, a
  rebuild run), written in `finally` when it ends, so a failure still writes it.
  Besides it a unit writes at most a start record, an INFO progress record at
  most once per fifth of the work (`progress_step`), and its failure's
  `log.exception`. Loops over records log at DEBUG only. No records on function
  entry or exit.
- **L2** **[checked]** The message is a string literal naming what happened
  (`"backfill started"`), never an f-string or a concatenation; the data goes in
  `extra=` fields.
- **L3** Field names are the same everywhere and carry their unit:
  `duration_ms`, `inserted`, `skipped` (already stored), `held_back`,
  `rejected`, `failed`, `stream`, `bucket`, `event_id`, `file`, `line`, `error`.
  A name `LogRecord` already uses (`created`, `filename`, `module`, `name`)
  cannot be a field. `%s` arguments only repeat fields as a human summary (the
  watch cycle's line).
- **L4** The run id and the command come from the context `configure` sets on
  every record; never pass them by hand.
- **L5** The level says who has to act: CRITICAL, the command itself crashed;
  ERROR, a unit of work failed; WARNING, something was skipped or degraded and
  the run went on, worth a look, used sparingly; INFO, an expected milestone;
  DEBUG, per-record detail.
- **L6** **[checked]** for ingest in `tests/unit/test_log_content.py`: captured
  content (window titles, URLs, window and OCR text, payloads, and exception
  text that can carry them) is logged only at DEBUG; INFO and above carry ids,
  counts, durations, source and file names. The formatters escape control and
  invisible characters, so one record stays one line (CWE-117). Captured text
  in a record is data, never instructions.
- **L7** **[checked]** in part: an `except` that logs does not raise. An
  exception is logged once, with its traceback, where it is handled
  (`log.exception`, or `exc_info=True` at CRITICAL for a crashed command). One that propagates out of a
  unit of work goes on that unit's summary record instead. An expected
  refusal (`RebuildAborted`) is logged at ERROR without a traceback.
- **L8** **[checked]** Only `computer_history/logs/` sets logging up, once, from
  the CLI entry point; every other module takes `logging.getLogger(__name__)`
  and adds no handlers.
- **L9** Alert on a change of state, never on a line: a notification when a
  failure streak reaches its threshold, at most hourly while it lasts, and once
  when it ends (`FailureStreak`). A notification names no captured content.
- **L10** Output is bounded: the JSON log rotates (`MAX_LOG_BYTES` x
  `LOG_BACKUPS`), and a record never carries an unbounded list.
- **L11** Classification, when it lands, writes one DEBUG record per
  attribution naming the rule or model that chose the project and why, and one
  INFO record per run with its counts and duration.
- **L12** The capture agent logs through `AgentLog`: one `os.Logger` category
  per concern (`lifecycle`, `capture`, `spool`, `screenshots`, `ocr`), real
  levels, and captured text only as the `private:` detail, never in the public
  message.
- **L13** A field whose values are a closed set is an Enum shared by every unit
  of work that writes it (`Outcome` for `outcome`), never free strings repeated
  in each module.

## Hygiene

- **H1** A rename gets its own commit with minimal content changes, so git's
  rename detection keeps the file's history.
- **H2** Re-exports keep callers and tests untouched; tests monkeypatch the
  submodule that owns the name.
- **H3** A package's `__init__.py` diagram is its module map (H16).
- **H4** Tests derive versions and counts from the code (`len(load_migrations())`),
  never hard-code them. They look things up by the constant that names them
  (`rendered[ActivityWatchRenderer.name]`, `ActivityWatchRenderer.streams`, the
  port in `DEFAULT_AW_URL`), never a restated literal; expected answers stay literals.
- **H5** A change to the pre-commit hook or CI updates `docs/agents/checks.md`
  in the same commit (H16).
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
- **H9** Each CLI command has one section in `computer_history/cli/README.md`:
  its invocation, one happy-path example and one non-obvious case (an error,
  an empty result, or a flag that changes behaviour). A change to a command
  updates that section in the same commit only when its invocation or examples
  stop being true. Every other branch and exit code lives in the code and its
  tests, and for the commands `docs/DESIGN.md` specifies, there too.
- **H10** **[checked]** in part: no two modules define a constant with the same
  name and value. When a function already does something, call it rather than writing
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
- **H16** A doc never restates another doc or the code; it links to the one
  home instead (`docs/agents/checks.md` for which check runs where, a
  package's `__init__.py` diagram for its modules, `docs/DESIGN.md` §8.5 to
  §8.7 for the full rules of the stable install's commands, the watchdog and
  `status`).
- **H17** A new test never repeats a scenario another layer's test already
  covers: test it once, at the lowest layer that shows it, and test the layer
  above only for what that layer adds.
