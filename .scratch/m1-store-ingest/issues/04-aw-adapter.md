# 04 — ActivityWatch adapter

Type: task
Status: open
Blocked by: 03

## Task

Pull from the AW HTTP API (`http://127.0.0.1:5600/api/0`, read-only) and
write through the store API. Only this adapter knows AW payload dialects.

- Discover window / AFK / Chrome buckets (patterns per AGENTS.md; hostnames
  vary — match by bucket type/client, not hard-coded names).
- Pull events since each source's cursor. **Settled-events rule:** ingest an
  event only once it is superseded by a newer event in its bucket or its end
  is older than the 120s stability margin (AW grows the current event in
  place; see map Notes).
- `source_id` = AW bucket + event id; payload stored verbatim in
  `observations.payload`.
- Normalization into `signals`: `app`/`title` from aw-window; `url`/`title`
  from aw-web with `domain` extracted from the URL; text hygiene per §3.2;
  leftovers into `extras` JSON. AFK events → observations only.
- Mapping code version constant (bumped whenever projection logic changes;
  read by rebuild-signals).

## Acceptance

Unit tests on captured fixture payloads for each bucket type (normalization
correctness, domain extraction, settled-events boundary cases). The M1
idempotency test: ingest a fixture range twice → second run inserts zero
rows and `status` counts are unchanged.
