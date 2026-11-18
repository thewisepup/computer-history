# 07 — backfill

Type: task
Status: open
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
