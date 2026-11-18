# 03 — Store write/read API

Type: task
Status: open
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
