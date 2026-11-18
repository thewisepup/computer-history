# 02 — Store: connection, migration runner, schema 001

Type: task
Status: open
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
