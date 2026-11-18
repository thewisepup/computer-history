# 02 — Cursor becomes opaque per-source ingest progress

Type: task
Status: resolved
Blocked by: 01

## Problem

The cursor is a UTC text timestamp in `ingest_cursors(source, last_seen)` and
six places each hold their own rule: `cursors.py` (get/set/init, forces
`utc_iso`), `insert_observations(advance_cursor=)` (the only safe way to
move it), AW ingest (600s rewind, min frontier over buckets), backfill
(`init_cursor` commits separately after the last chunk), `store/status`
(returns it as a datetime; status shows lag = now − cursor and uses it as
the gap-window end), `plan_backfill` (`to_utc(cursor)`), `cli/backfill`.
M2's spool cursor is `(file, offset)`; every one of those breaks.

## Task

Replace the cursor with an ingest-progress record the store keeps without
interpreting:
- `position`: opaque text the source encodes/decodes (AW: canonical UTC
  timestamp; M2: file + offset).
- `settled_until`: optional UTC time up to which the source's data is
  complete (AW: same instant as position). Status's gap window and backfill
  planning use this, never `position`.
- `advanced_at`: when progress last moved (status freshness).
New migration (next number, derived — don't hard-code counts in tests)
moves `ingest_cursors` rows into the new table (position = settled_until =
last_seen) and drops the old table. Observations untouched.

Progress only ever moves inside the same transaction as a batch insert.
Both modes go through that one path: "advance" (incremental) and "set only
if none" (backfill's first-time init). Remove `set_cursor`/`init_cursor` as
public writers. Backfill's init happens with its last chunk's batch, or an
equivalent single atomic write in the store — decide and record why.

The AW adapter owns everything timestamp-specific about its position
(encoding, the 600s overlap rewind, min frontier over buckets). Nothing in
`store/`, `cli/`, or backfill planning decodes a position.

Status output: keep the same information (per-source settled-until time and
lag, gap window up to settled_until). Update `cli/README.md` if any output
line changes.

## Acceptance

- Migration test: a DB at the previous version with cursors migrates to the
  new table with identical AW resume behaviour.
- Store tests: advance and set-if-none are atomic with their batch (failure
  rolls both back); set-if-none never overwrites.
- AW adapter/backfill tests stop asserting raw cursor strings where an
  outcome assertion works ("resume reads nothing twice / misses nothing").
- A test shows the store round-trips a non-timestamp position (e.g.
  `"2026-11-18T10.jsonl:48213"`) with `settled_until` set separately, and
  status/backfill planning still work for that source.
- Full suite + ruff green.

## Answer

**Built.** Migration `003_ingest_progress.sql` replaces `ingest_cursors` with
`ingest_progress (source PK, position TEXT NOT NULL, settled_until TEXT,
advanced_at TEXT NOT NULL)`, copying each cursor as position = settled_until =
advanced_at = last_seen, then dropping the old table. Observations are not
touched. `store/cursors.py` is gone and `store/progress.py` owns the table.

Store interface (all the store exports for progress):

```python
Progress(source, position: str, settled_until: datetime | None, advanced_at: datetime)
ProgressUpdate(source, position: str, settled_until=None, only_if_none=False)  # validates on construction
get_progress(conn, source) -> Progress | None
insert_observations(conn, observations, *, progress: ProgressUpdate | None = None) -> InsertResult
InsertResult(inserted, skipped, progress_moved=False)
SourceSummary(..., settled_until, advanced_at)   # replaces .cursor
```

`insert_observations` is the only way progress moves. It writes the update in
the batch's own transaction through `progress.write_with_batch`, which is not
re-exported and raises if no transaction is open. Advance overwrites (it may
move backwards, e.g. a late, still-growing AW event); `only_if_none` is
`ON CONFLICT DO NOTHING`. `advanced_at` is the batch's `ingested_at`. The store
never parses `position`; `settled_until` goes through `utc_iso`.

AW adapter: new `activitywatch/position.py` owns everything timestamp-specific:
`progress_at(source, frontier, *, only_if_none=False) -> ProgressUpdate`
(position = utc_iso(frontier), settled_until = frontier),
`resume_start(position) -> datetime` (position minus
`RESUME_OVERLAP_SECONDS`, renamed from `CURSOR_OVERLAP_SECONDS`, still 600).
`pull.py` gets `pull_source(client, source, *, start, end, now) ->
SourcePull(observations, held_back, frontier)` (the minimum frontier over
buckets lives here), `ingest.py` gets `outcome_of(pulled, written) ->
IngestOutcome`, and `ingest_source` becomes pull_source + one
`insert_observations`. Backfill planning takes `progress=` (was `cursor=`),
`BackfillPlan.settled_until` + `.has_progress` (was `.cursor`),
`BackfillResult.progress_set` (was `.cursor_set`).

**Decisions.**

- *Backfill sets first-time progress in the last chunk's own commit*, not in a
  separate write afterwards. `run_backfill` now pulls each chunk with
  `pull_source`, works out `complete_until` (first incomplete frontier, else
  plan end) before writing, and passes `progress_at(..., only_if_none=True)`
  to the last chunk's `insert_observations`. Why: it keeps the rule with no
  exception (progress only moves with a batch), removes the crash window
  where every chunk was committed but progress was unset, and costs no extra
  commit. The pull/write split it needs is exactly the seam ticket 03's
  runner wants (adapter pulls, runner writes batch + progress), and no
  position encoding leaked into backfill: it calls the AW adapter's
  `progress_at`. A test asserts N chunks make N writes, only the last one
  carries progress, and a failed last write leaves progress unset.
- *Backfill tries the first-time write only when the plan saw no
  settled_until*; `only_if_none` in the store covers everything else (a
  concurrent `ingest --watch`, or a source whose progress has no settled
  time). "Existing progress is never moved" is now enforced in SQL, not by
  the caller.
- *Status lag still reads settled_until*, as the cursor did. `advanced_at`
  is used only when a source has progress but no settled time: the line reads
  `settled until - (progress moved 30s ago)` instead of the misleading "never
  ingested". The gap window ends at settled_until, else at the latest
  observation.
- *User-facing wording moved from "cursor" to "progress / settled until"* in
  status and backfill output (`settled until <t> (<lag>)`, `progress set:
  settled until <t>; ...`, `progress unchanged: ...`, `progress not set: ...`,
  `up to its settled-until time <t>`, `no ingest progress yet`) and in
  `--end`'s help. Same information, and the term is right for a spool
  position. `cli/README.md` and DESIGN.md (§2 layout, §3.5 schema + rules, §4
  adapter contract, M2/M4 wording) updated; README examples now say schema v3.
- *`InsertResult` gained `progress_moved`* (default False), so backfill learns
  whether its set-if-none write won without a racy re-read. Tests that
  compared with bare `(n, m)` tuples now compare with `InsertResult(n, m)`.
- *`cursors.py` was deleted and `progress.py` written new*, not renamed: no
  line of the old module survives, so no history is worth keeping.
- `tests/test_store.py` no longer hard-codes schema version 2, and the CLI
  test derives `schema v{SUPPORTED}`. The migration tests find the progress
  migration by name, so they keep working when 004 lands.

**Tests.** New `tests/test_progress.py`: opaque position round-trip with
settled_until set separately, a position with no settled time, advance
overwrites, set-if-none sets / never overwrites, no write outside a batch
transaction, the store exports no progress writer, bad updates rejected,
status summary and backfill planning on an opaque position, the migration
(cursor becomes progress, observations byte-identical, old table gone), and
resume after migration matching resume on today's schema (same AW query
start, B skipped, C inserted, A never re-read). `test_store_api`: failure
rolls back the batch with either advance or first-time progress. `test_cli`:
status for an `ax-text` source with a spool position (lag and gap window
from settled_until) and a source with no settled time. AW and backfill tests
now assert settled_until datetimes and outcomes instead of raw cursor strings.

**Review fixes.**

- *advanced_at only moves when progress does.* The advance upsert now has
  `WHERE position IS NOT excluded.position OR settled_until IS NOT
  excluded.settled_until`, so re-sending the same position and settled time
  leaves `advanced_at` alone and reports `progress_moved=False`. Without it a
  stalled source, especially one with `settled_until` NULL like the M2 spool,
  looked fresh in status. Tests cover a repeat with and without a settled
  time, and a refresh when the position changes, the settled time changes,
  or it is cleared.
- *Backfill tells "has progress" apart from "has a settled time".*
  `plan_backfill` now takes `progress: Progress | None`, and `BackfillPlan`
  gained `has_progress`. A source whose progress has no settled time is
  planned up to now (the same bound as no progress), because the store cannot
  say where its coverage ends and re-reading is idempotent. Backfill never
  tries first-time progress for it, and the CLI reports `up to now (its ingest
  progress has no settled-until time)` and `progress unchanged: it has no
  settled-until time` instead of "another ingest set it meanwhile". Tested
  with the opaque-position fixture (store level and CLI).
- *SourcePull and pull_source moved into pull.py*, next to `pull_bucket`.
  `ingest.py` keeps the conversion as `outcome_of(pulled, written)`. The
  package diagram notes that pull.py takes the earliest bucket frontier.
- *The backfill module docstring is trimmed* to what the module does: chunked
  commits, oldest first, and the last chunk's first-time progress.
- *insert_observations takes `now`*, which stamps `ingested_at` and
  `advanced_at`. `run_backfill` passes its clock (one reading per chunk, shared
  by the pull and the write). The round-trip test now asserts the exact
  `advanced_at`, and the backfill test asserts it equals the clock.

**Left as-is (by decision).**

- The migration fills `advanced_at` from `last_seen`: the old table never
  recorded when a cursor moved, and last_seen is the closest honest value.
- Advance can move progress backwards when two ingests race. That predates
  this ticket (set_cursor overwrote too).
- `ingest_source`'s explicit-range path stays; ticket 03's runner removes it.
- DESIGN.md's "per-source cursor freshness" is a ticked M1 checklist item, so
  it stays as the historical record.
