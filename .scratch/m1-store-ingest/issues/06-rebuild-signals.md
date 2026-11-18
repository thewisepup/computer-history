# 06 — rebuild-signals

Type: task
Status: open
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
