# 03 — One ingest runner behind a source adapter seam

Type: task
Status: resolved
Blocked by: 02

## Problem

Three loops wrap `ingest_source`: `run_cycle`/`watch` in `cli/ingest.py`
(production poll + error policy: AWError / OperationalError end the cycle,
earlier sources stay committed), `ingest_all` (only tests call it, no error
policy), and `run_backfill` (chunk loop + incomplete rule + progress init),
with `cli/backfill._backfill_one` re-deriving "incomplete" and why the cursor
was or wasn't set. `ingest_source` hides a mode flag in optional
`start`/`end`. Tests reach the real loops only by monkeypatching
`cli_ingest.ingest_source`, `cli_ingest.AWClient`, `backfill_module.ingest_source`.

## Task

Introduce a source adapter seam and one source-agnostic runner in
`sources/`:
- The adapter Protocol is the minimal set of operations a source needs:
  name its streams (AW: aw-window/aw-afk/aw-web), pull observations after a
  progress position, pull an explicit range, and report the new position /
  settled_until / held-back count. Its failure is one exception family the
  runner understands as "source unavailable" (AWError joins it). The AW
  adapter implements it; backfill-planning facts it needs (history start,
  earlier-history probe) become adapter operations if that is what keeps the
  runner source-agnostic.
- The runner owns: polling every stream of every adapter (incremental
  mode), ingesting a planned range in chunks (backfill mode, including the
  incomplete rule and the set-if-none progress from ticket 02), the
  per-stream error policy, and returning structured outcomes. The watch loop
  (interval, injected sleep/clock) lives here too; the CLI only formats and
  logs its reports.
- The CLI keeps constructing clients/adapters and connections (layering rule
  in `test_standards.py`) and passes them in. CLI modules end up as parse →
  one call → format → exit code.
- Delete `ingest_all` and the duplicated incomplete/cursor reasoning in
  `cli/backfill.py`. Explicit modes instead of a mode inferred from optional
  args.

## Acceptance

- A small in-memory fake adapter in tests (second adapter makes the seam
  real) drives the runner: source-unavailable mid-cycle keeps earlier streams
  committed and reports the failed stream; DB lock likewise; backfill chunks
  with an incomplete chunk report it once and set progress correctly.
- Existing AW behaviour unchanged end to end (fake_aw-based tests still pass,
  adjusted to the new entry points). No test monkeypatches `ingest_source`
  or module attributes to reach the loops.
- DESIGN.md package layout, package `__init__` flow diagrams,
  `cli/README.md` updated. Full suite + ruff green.

## Answer

**Built.** `sources/` is now the runner package with a source-agnostic core;
ActivityWatch is one adapter behind it.

```
sources/contract.py   Source, HistorySource (Protocols), Pull, SourceUnavailable
sources/commit.py     commit_pull (the one write step), StreamFailure, FailureKind, failure_of
sources/runner.py     poll, watch, CycleSummary, IngestOutcome
sources/backfill.py   planning + run_backfill and its reports (see Review fixes)
sources/activitywatch/adapter.py   ActivityWatch (implements HistorySource)
sources/activitywatch/history.py   history_floor, history_before (moved from backfill.py)
```

Adapter Protocol (the core one is two methods):

```python
class Source(Protocol):
    def streams(self) -> Sequence[str]: ...
    def pull_after(self, stream, position: str | None, *, now) -> Pull: ...

class HistorySource(Source, Protocol):           # backfill only
    def parts(self, stream) -> tuple[str, ...]: ...
    def history_start(self, stream) -> datetime | None: ...
    def history_before(self, stream, start) -> tuple[tuple[str, datetime | None], ...]: ...
    def pull_range(self, stream, start, end, *, now) -> Pull: ...

Pull(observations, held_back, position: str | None, settled_until: datetime | None)
class SourceUnavailable(RuntimeError)            # AWError subclasses it
```

Runner interface:

```python
poll(conn, sources, *, now=None) -> CycleSummary(at, outcomes: {stream: IngestOutcome}, failures)
watch(conn, sources, *, report, interval=60, clock=None, sleep=None) -> NoReturn
run_backfill(conn, source, plans, *, clock=None, on_chunk=None, on_stream=None) -> BackfillRun
IngestOutcome(inserted, skipped, held_back, settled_until)
StreamFailure(stream | None, error, kind: FailureKind.SOURCE | DATABASE_BUSY | DATABASE)
ChunkDone(stream, index, total, chunk, inserted, skipped, held_back, incomplete_from, seconds)
BackfillResult(plan, chunks_done, inserted, skipped, held_back, seconds, incomplete,
               complete_until, progress: BackfillProgress | None)
BackfillProgress: SET | KEPT | KEPT_UNSETTLED | NOT_COVERED | SET_MEANWHILE
BackfillRun(results, failure=None, interrupted=False)
```

Deleted: `ingest_source`, `ingest_all`, `activitywatch/ingest.py`, `SourcePull`,
`outcome_of`, `progress_at`, `cli.run_cycle`, `cli.watch`, `cli.CycleSummary`,
and `cli/backfill._backfill_one`'s incomplete/progress reasoning.

**Decisions.**

- *Streams are names, not handles.* `ActivityWatch` caches the bucket listing
  and discovered sources from its latest `streams()` call (made lazily on the
  first pull if needed). That keeps the Protocol to plain strings (what the
  store already keys by) and keeps backfill at one bucket listing per run. A
  stream it has no buckets for raises `AWError`.
- *The runner owns progress semantics, the adapter owns the encoding.* A pull
  returns `position` + `settled_until`; the runner builds the
  `ProgressUpdate` (advance for polls, `only_if_none` for backfill's last
  chunk). `position=None` means "leave progress alone": AW returns it only
  for a source with no buckets; the M2 spool returns it when it consumed
  nothing (otherwise an advance would clear `settled_until`). The 600s
  rewind stays inside `ActivityWatch.pull_after` via `resume_start`.
- *First-time backfill progress uses the first incomplete chunk's own pull*
  (its position and settled_until), else the last chunk's. Range pulls carry
  a position, so the runner never encodes a time into a position and
  `HistorySource` needs no `position_at` operation. Tested with the fake
  source (position comes from chunk 2's pull, not chunk 3's).
- *Backfill operations are a separate Protocol.* The spool will implement
  only `Source`. `parts` exists only so the plan line keeps its
  `(N buckets)` count; dropping it would have changed output for no gain.
- *Error policy.* Poll: `SourceUnavailable` skips the rest of that source's
  streams and **other sources still run** (AW down must not block the M2
  spool); `sqlite3.OperationalError` ends the cycle; other database errors
  propagate (as before, so a corrupt DB stops `--watch` loudly). Backfill:
  any `SourceUnavailable`, `sqlite3.Error` or Ctrl-C stops the run and is
  returned in `BackfillRun` with the streams that committed chunks (the CLI
  used to catch these itself). With one adapter, behaviour is unchanged.
- *watch measures the cycle with the injected wall clock*, clamped to
  `[0, interval]`, instead of `time.monotonic`. One injected clock serves both
  `now` and the delay, and the tests no longer patch `time.monotonic`; a clock
  step during a cycle can only shorten or lengthen one sleep within the
  interval.
- *Chunk and stream timings come from the runner's clock* (`ChunkDone.seconds`,
  `BackfillResult.seconds`), so the CLI holds no timing state. Same output
  format.
- *Vocabulary.* "Stream" is what the store calls a source; adapters are
  "sources". `IngestOutcome.frontier` became `settled_until`, and
  `BackfillPlan.source: AWSource` became `stream` + `parts`. `BackfillResult`
  now holds its `plan`.
- *Projection (ticket 04).* Observations still arrive with signals from the
  adapter (`pull.py` calls `project_signal`). The runner has one write call
  per stream for poll and backfill (`insert_observations` in `_poll_stream`
  and `_backfill_stream`), so routing to each adapter's projector fits
  either as a `Source` method or as a step just before those two writes.
- `status` now lists streams via `ActivityWatch(client).streams()`.
- `poll` stamps `ingested_at`/`advanced_at` with the poll's `now`.

**CLI output.** Unchanged: ingest lines, watch log lines, backfill chunk,
summary, totals, failure and hint lines are byte-for-byte the same formats.
`cli/README.md` and the `cli/__init__` diagram now say commands go through
the ingest runner; `cli/__init__` no longer re-exports `run_cycle`, `watch`,
`CycleSummary`, `POLL_INTERVAL_SECONDS` (they live in `sources`).

**Tests.** New `tests/fake_source.py` (an in-memory spool-like adapter:
offset positions, unsettled captures, down streams, a before-pull hook) and
`tests/test_runner.py` (16 tests): poll resume and position=None, held-back
captures, source unavailable mid-cycle with a second adapter (ActivityWatch)
still polled, failure to list streams, DB lock mid-cycle (earlier stream
kept, cycle ended, recovery), hard DB errors propagate, watch delays and
clamp, backfill incomplete chunk reported once with progress from its pull,
one commit per chunk with progress only in the last (SQL trace), source down
mid-backfill, DB lock before the last chunk, Ctrl-C, NOT_COVERED,
SET_MEANWHILE, KEPT. AW, backfill, CLI, progress and rebuild tests use
`poll` / `pull_range` / `run_backfill` with `ActivityWatch(fake)`. No test
monkeypatches `ingest_source`, `insert_observations`, `get_progress` or
`time`: lock failures use a real second connection, the hard backfill error
uses a SQLite trigger, the planning read failure uses a dropped table, and
the `--watch` Ctrl-C test raises from the fake AW mid-cycle. CLI tests still
monkeypatch `AWClient`, since the CLI constructs it. 548 pytest, ruff clean,
POC unittest 12 OK.

**Review fixes.**

- *Backfill lives in one module.* `run_backfill`, `BackfillResult`,
  `BackfillProgress`, `BackfillRun` and `ChunkDone` moved into
  `sources/backfill.py` beside planning; `runner.py` keeps poll and watch.
  The shared pieces went to a new flat module `sources/commit.py`:
  `commit_pull(conn, stream, pulled, *, now, progress_from=None,
  only_if_none=False) -> Committed(inserted, skipped, progress_sent,
  progress_moved)` (builds the `ProgressUpdate`, with "no position, no
  update" in one place) and `failure_of(stream, exc) -> StreamFailure`
  (source unavailable / operational / other database error). Chosen over a
  `runner/` package because poll and backfill are one module each and the
  shared step is small; a package would add an `__init__` and a rename for
  no extra separation. Each caller keeps its own policy on top of the shared
  classification: poll re-raises `DATABASE` and stops the cycle on
  `DATABASE_BUSY`, backfill stops on any.
- *Ctrl-C anywhere in the run loop*, including the `on_stream` callback,
  returns `interrupted=True` with what committed (tested with a callback
  that raises `KeyboardInterrupt`).
- *`BackfillProgress.NO_POSITION`*: the plan covered the history but the
  source's pull had no position, so no update was sent. `SET_MEANWHILE` now
  means only "sent, but another ingest got there first". The CLI prints
  "progress not set: the source reported no position to resume from".
- *A chunk with held-back events but no settled time is incomplete from its
  start.* `complete_until` is the first incomplete point, else the plan's
  end (as before this ticket).
- *watch* paces with an injectable `monotonic` timer and uses `clock` only
  for each cycle's `now`. A cycle longer than the interval starts the next
  one at once.
- *Duplicate streams are refused* with `ValueError`: poll checks each
  source's streams before reading any of them, and backfill refuses a
  repeated stream in its plans or in a source's listing.
- *Planning returns `Planning(plans, failure: StreamFailure | None)`*, so the
  CLI formats one failure type for planning and the run
  (`cli/backfill._failed`). Messages are unchanged: "cannot read <db>: ..."
  for planning, "backfill stopped: database error: ..." (+ busy hint) for
  the run. The docstring caveat is gone; `cli/README.md` already states the
  create-after-planning rule.
- *`pull_source` returns `SourcePull(observations, held_back, frontier)`*
  again, beside its producer; `ActivityWatch` turns it into a `Pull` and
  calls `position_at`, so the fetch stage knows nothing about positions.
- `status` catches `SourceUnavailable`. The ActivityWatch hint lives once,
  in the new `cli/sources.py` (`SOURCE_HINT`, `source_failed`), used by
  ingest and backfill. The adapter's caching docstring sentence is gone.
- Runner tests pass `interval=` (from `POLL_INTERVAL_SECONDS`) explicitly.
- Tests: 569 pytest (new: watch pacing, slow cycle, duplicate streams in poll
  and backfill, Ctrl-C in `on_stream`, NO_POSITION, held-back with no
  settled time), ruff clean, POC unittest 12 OK.
