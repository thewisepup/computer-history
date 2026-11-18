# 06 — rebuild-signals

Type: task
Status: resolved
Blocked by: 04

## Task

`computer-history rebuild-signals`: wipe the `signals` table and re-project
every content observation from raw `observations` using the current adapter
mapping code; update the mapping-version meta row. One transaction (or
batched with a final atomic swap) so a crash never leaves signals
half-built. `observations` is never touched.

## Acceptance

Test: ingest fixtures → snapshot signals → rebuild → result is identical
row-for-row (the M1 "result identical" checkbox). Meta row records the
mapping code version. AFK observations still produce no signal rows after
rebuild.

## Answer

Done (Opus 5.5 implementer + medium code review with fix round, 2026-11-17).

- `store/rebuild.py`: `rebuild_signals(conn, project, *, mapping_version,
  batch_size=1000, allow_shrink=False) -> RebuildResult`. The seam: store/
  cannot import sources/, so the projector is passed in; the CLI wires
  `project_signal` + `MAPPING_VERSION` together. One transaction: DELETE,
  streamed re-projection (id-ordered cursor, batched executemany),
  `set_mapping_version`. Refuses to run inside an open transaction.
- Safety rails: malformed payloads are logged/skipped/counted (first 20 ids,
  then "(and N more)"); abort + rollback when failures exceed half the
  possible content rows, checked incrementally so a totally broken projector
  stops ~halfway, not after a full scan; abort when the rebuild would keep
  under half the existing signals (≥50-signal stores) even with zero
  failures — catches a projector silently returning None — overridable with
  `--allow-shrink` for legitimate mapping changes.
- CLI: before/after counts, mapping version ("was none" on first), skipped
  report; refuses a nonexistent --db-path (never creates a store); locked-DB
  errors at open or during rebuild print a shared hint, exit 1, no
  traceback (cmd_ingest's open path shares `_open_store`).
- Known trade-off: BEGIN IMMEDIATE is held for the whole rebuild, so ingest
  is blocked while it runs (documented in docstring + CLI help; the watch
  loop logs and retries). Upgrade path if rebuild time ever matters: build
  into a shadow table outside the lock, swap in one short transaction.
- Identity verified: rebuilt rows byte-identical to ingest's at batch sizes
  1/2/1000; timestamps copied as stored, never re-normalized; AFK payloads
  never parsed; rollback tested via injected failure, interrupt, and a
  concurrent reader seeing old signals mid-rebuild.
- 194 tests green, ruff clean, POC unittest OK.
