# 05 — CLI: ingest + status

Type: task
Status: resolved
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

## Answer

Done (Opus 5.5 implementer + medium code review with fix round, 2026-11-17).

- `ingest`: one poll via `run_cycle(conn, client)` → per-source
  `inserted/skipped/held back` lines. Partial cycles keep their counts: on a
  mid-cycle failure the committed sources' outcomes are printed, then
  `error on <source>: …` (exit 1). `--aw-url` option; AW-down → clean stderr
  message, exit 1, no traceback.
- `ingest --watch`: 60s loop (`POLL_INTERVAL_SECONDS`), one logged line per
  cycle; survives `AWError` AND transient `sqlite3.OperationalError` (lock
  contention) with WARNING + retry; harder `DatabaseError` (corruption) stays
  fatal; retry message logs the actual computed sleep; Ctrl-C exits 0.
- `status`: READ-ONLY (`store.connect_readonly()`, SQLite `mode=ro` — never
  creates or migrates; older schema → "ingest will migrate" note, newer →
  "upgrade" note; empty `-wal`/`-shm` sidecars from a ro reader are expected
  and removed by the next writer — tested). Reports DB path/size/schema, AW
  reachability (5s probe timeout), per-source counts + cursor lag (with the
  still-growing-event caveat), coverage gaps ≥5min in the 24h up to each
  source's cursor (or latest observation if cursorless) — phrased
  "unobserved", never "idle" — and table counts. Always exits 0.
- `SourceSummary` gained `earliest_started_at` (folded into the one query;
  gap windows never start before recording began).
- `tests/fake_aw.py`: shared FakeAW for adapter + CLI tests.
- 165 tests green, ruff clean, POC unittest OK. Live read-only smoke run of
  `status` printed DB-not-yet-created + AW reachable with all three sources.
