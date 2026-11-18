# 07 — backfill

Type: task
Status: resolved
Blocked by: 05

## Task

`computer-history backfill`: one-time ingest of Brandon's existing AW
history (months of data) through the same idempotent store path.

- Chunked time ranges (≤31 days per AW query) from the earliest event in
  each bucket up to the current cursor; progress logging per chunk.
- Same settled-events + dedup semantics as `ingest` — re-running backfill
  adds zero rows.
- Then actually run it on this Mac against live AW and record the resulting
  row counts per source in this ticket's Answer.

## Acceptance

Test with multi-chunk fixture ranges (idempotency across chunk boundaries).
Live run completed; counts recorded; `status` shows full historical
coverage with gaps honestly reported.

## Answer

Done (Opus 5.5 implementer + medium code review with fix round, 2026-11-17).

- `sources/backfill.py`: `plan_backfill` / `run_backfill` (+ `BackfillPlan`,
  `BackfillResult`, `Chunk`, `BACKFILL_CHUNK = 7 days`). Range: earliest
  bucket `created` (floored to local midnight) → the source's cursor if set,
  else now; a limit=1 probe warns if events exist before the floor (an
  unreadable probe event counts as "earlier history exists" — fail safe, no
  cursor set). Chunks oldest-first through `ingest_source(start, end)`, one
  commit each; only the final chunk can be incomplete (held-back events),
  reported with a note, never looped on.
- Cursor design: explicit-range ingest never touches cursors, so backfill
  sets it afterwards via new `store.init_cursor` (single-statement
  `ON CONFLICT DO NOTHING` — a cursor written meanwhile by `ingest --watch`
  wins; never set after a partial `--start` range or an interrupted run).
  Set to the first incomplete chunk's frontier, else range end: every event
  before the cursor is stored, and the next `ingest` continues without
  re-reading history (tested).
- CLI: `backfill [--start ISO] [--end ISO] [--dry-run]` + the usual
  `--db-path`/`--aw-url`. Plans (all AW calls) before creating/opening the
  DB — an AW outage creates nothing; missing DB is otherwise created (may be
  the first command ever run). Mid-run `sqlite3.Error`/`AWError`/Ctrl-C print
  totals-so-far + a resume hint (only when ≥1 chunk committed, never in
  --dry-run), exit nonzero, no traceback. One bucket listing per run
  (`discover_sources(buckets=)`).
- **Live run on this Mac (production DB, 2026-11-17):** history starts
  2026-11-12, one chunk per source. Inserted 82 aw-afk, 2,447 aw-web,
  3,180 aw-window = 5,709 observations, 5,627 signals; 1 held back per
  source (the still-growing current events); cursors set to each frontier.
  **Re-run inserted 0 / skipped all 5,709** (idempotency on real data).
  `status`: 5.0 MB DB, schema v1, all sources fresh; aw-web shows expected
  "unobserved" gaps (browser not in use); aw-window/aw-afk gap-free for 24h.
- 223 tests green, ruff clean, POC unittest OK.
