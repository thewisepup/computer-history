# 02 — Store: connection, migration runner, schema 001

Type: task
Status: resolved
Blocked by: 01

## Task

The database layer: path resolution, connection helper, `user_version`
migration runner, and migration 001 containing the complete §3 schema.

- DB path resolution: default
  `~/Library/Application Support/ComputerHistory/history.db`, overridable by
  `COMPUTER_HISTORY_DB` env var and a `--db-path` CLI flag (flag wins).
  Parent directory created on first open.
- Connection helper: WAL mode, `foreign_keys=ON`, sensible busy timeout.
- Migration runner (~30 lines): read `PRAGMA user_version`; apply each
  numbered `computer_history/store/migrations/NNN_*.sql` above it in order,
  each inside one transaction together with the `user_version` bump.
- `001_initial_schema.sql`: `observations`, `signals`, signals-mapping meta
  table, `projects`, `work_types`, `blocks`, `block_tags`, `reviews`,
  `suggestions`, `ingest_cursors`, `classification_runs`, and the
  `block_evidence_v` view — exactly as `docs/DESIGN.md` §3 specifies,
  including `UNIQUE (source, source_id)` and signals PK = observation id.

## Acceptance

Tests: fresh tmp DB → full schema present, `user_version = 1`; running
migrations again is a no-op; opening the same file twice is safe.

## Answer

Done (Opus 5.5 implementer + medium code review, 2026-11-17).

- `store/paths.py`: `resolve_db_path` (flag > `$COMPUTER_HISTORY_DB` > default;
  empty = unset; `~` expanded), `default_db_path`, `DB_ENV_VAR`.
- `store/db.py`: `connect()` (WAL enforced, FKs on, 5s busy timeout,
  `sqlite3.Row`, auto-migrate), `transaction()` (**connections use
  `isolation_level=None` — every multi-statement write MUST go through
  `with transaction(conn):`**; BEGIN IMMEDIATE; commit guarded), migration
  runner (statement-split, never `executescript`; atomic per migration;
  re-checks `user_version` under the write lock; validates sort/contiguity
  of any caller-supplied list; default migrations cached per process).
- `store/migrations/001_initial_schema.sql`: all §3 tables + indexes +
  `block_evidence_v` (half-open overlap, zero-length-at-start included).
  Deviations recorded: `classification_runs.range_start/range_end` instead
  of one `range` column; `signals_meta(id=1, mapping_version)` seeded by
  ticket 03/06; `block_tags` PK `(block_id, tag)` with cascade; no CHECK
  constraints on status/source (new source must not need schema change).
- `store/timefmt.py`: `utc_iso()` — the ONE canonical timestamp format
  (`YYYY-MM-DDTHH:MM:SS.ffffffZ`); TEXT comparisons in the view depend on
  it; naive timestamps rejected. **Every writer in tickets 03+ must use it.**
- Packaging verified: wheel ships the .sql; works from site-packages.
- Review fixes: COMMIT inside the rollback guard; caller-supplied migration
  lists validated; `sqlite_master` (3.33-safe) in tests; regex allows 4+
  digit versions and hyphens; default migrations cached; AGENTS.md Storage
  row updated.
- 30 tests green, ruff clean.
