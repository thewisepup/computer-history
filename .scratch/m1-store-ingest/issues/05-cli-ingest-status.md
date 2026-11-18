# 05 — CLI: ingest + status

Type: task
Status: open
Blocked by: 04

## Task

- `computer-history ingest`: one poll cycle (all AW sources, settled events
  since cursors, write, advance cursors), logging inserted/skipped counts.
  `--watch` loops every 60s in-process until interrupted; survives transient
  AW API failures (log and retry next cycle, never crash the loop).
- `computer-history status`: AW API reachability; per-source cursor
  freshness (human-readable lag); coverage gaps over a recent window
  reported as warnings, never guessed as idle; row counts; DB path and file
  size.
- Both honor `--db-path` / `COMPUTER_HISTORY_DB`.

## Acceptance

Tests: ingest-then-status against a tmp DB with fixture data; a gap in
observations is reported as a coverage warning; `--watch` loop handles an
unreachable AW without exiting (unit-testable cycle function).
