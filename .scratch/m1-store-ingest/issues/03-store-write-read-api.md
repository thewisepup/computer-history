# 03 — Store write/read API

Type: task
Status: resolved
Blocked by: 02

## Task

The internal Python seam everything else calls; only `store/` knows SQL.

- `insert_observations(conn, rows)`: the single write path for raw data.
  One transaction per batch; each observation and its signal row written
  together; duplicates on `(source, source_id)` silently skipped (idempotent
  re-ingest); AFK observations get **no** signal row (§4.3 — AFK is state,
  not content). Returns counts (inserted / skipped) for logging.
- Cursor API: `get_cursor(conn, source)` / `set_cursor(conn, source,
  last_seen)`, advanced in the same transaction as the batch it covers.
- Read queries that `status` (ticket 05) will need: latest observation per
  source, row counts, observed-time gap detection over a recent window.

## Acceptance

Tests: dedup on re-insert adds zero rows; observation+signal atomicity (a
failed signal write rolls back its observation); AFK rows produce no signal;
cursor round-trips.

## Answer

Done (Opus 5.5 implementer + medium code review, 2026-11-17).

Public API (all from `computer_history.store`), for tickets 04/05/06:

- Types: `Observation(source, source_id, started_at, ended_at, payload, signal=None)`
  (frozen dataclass; `signal=None` for AFK), `Signal(app, domain, url, title,
  text, extras)` (timing copied from the owning observation — cannot
  disagree), `Cursor(source, last_seen)`, `InsertResult(inserted, skipped)`.
- `insert_observations(conn, observations, *, advance_cursor: Cursor | None)`
  — one transaction for batch + cursor (the crash-safety seam); dedup via
  `ON CONFLICT DO NOTHING` (only the uniqueness conflict is skipped); signal
  written iff its observation was newly inserted; validates source,
  source_id, timestamp order, canonical timestamps and the cursor BEFORE the
  write lock; refuses (RuntimeError, caller's transaction intact) when called
  inside `transaction()`. Cursor still advances on an all-duplicate batch.
- `get_cursor` (canonical UTC string — what adapters pass to source APIs) /
  `set_cursor` (plain upsert; may move backwards — re-ingest is idempotent);
  `get_mapping_version` / `set_mapping_version` (single id=1 row); setters
  are single statements and join an enclosing `transaction()` (ticket 06
  uses this).
- Reads: `source_summary(conn)` (count, latest ended_at, cursor — datetimes),
  `table_counts(conn)`, `find_gaps(conn, source, start, end,
  min_gap_seconds=0)` (merges overlapping events; zero-length events are no
  coverage; clips to [start, end)). `to_utc()` added alongside `utc_iso()`.
- Review fixes: requires-python bumped to >=3.11 (ruff target py311) —
  fromisoformat on 3.10 would reject common fraction precisions; nested-call
  guard made explicit and non-destructive; cursor validated pre-lock;
  empty `source` rejected; `get_cursor` string-vs-datetime contract
  documented; AGENTS.md test command updated.
- Notes for ticket 05: a status window ending at "now" always shows a
  trailing ~120s gap (settled-events margin) — end the window at the cursor
  or use min_gap_seconds > margin. `find_gaps` scans all rows before `end`;
  fine at M1 volume.
- 63 tests green (6 cli + 24 store + 33 API), ruff clean, POC unittest 12 green.
