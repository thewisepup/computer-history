# 02 — Cursor becomes opaque per-source ingest progress

Type: task
Status: open
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
