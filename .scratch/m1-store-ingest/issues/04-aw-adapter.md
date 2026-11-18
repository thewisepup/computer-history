# 04 — ActivityWatch adapter

Type: task
Status: resolved
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
  `observations.payload` — verbatim up to a JSON round-trip (AW's key order
  and values kept; whitespace/number spelling/`\u` escapes are Python `json`'s),
  since events arrive inside one list response.
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

## Answer

Done (Opus 5.5 implementer + medium code review with fix round, 2026-11-17).

Public API (from `computer_history.sources`): `AWClient` (stdlib urllib,
GET-only, `AWError` on any failure; `AWApi` Protocol for fakes),
`discover_sources` (by bucket TYPE: currentwindow/afkstatus/web.tab.current →
aw-window/aw-afk/aw-web; multiple buckets per source), `pull_bucket`,
`ingest_source(conn, client, source, *, start, end, now) -> IngestOutcome`,
`ingest_all`, `project_signal(source, payload dict|str)` (reusable by ticket
06; None for AFK), `extract_domain`, `clean_text`, `clean_url`,
`IngestOutcome(inserted, skipped, held_back, frontier)`. Constants:
`STABILITY_MARGIN_SECONDS=120`, `CURSOR_OVERLAP_SECONDS=600`,
`MAPPING_VERSION=1`.

Key semantics (deviations from the ticket sketch, with reasons):

- **Start-based ownership, not end-based cursor.** AW clips returned events
  to the query range and dedup keeps the first stored copy forever, so an
  end-based cursor + overlap would permanently store truncated payloads.
  Instead: an event belongs to the pull whose range contains its START;
  queries go from start−1s; events reaching an explicit query end are
  re-fetched whole individually. Cursor invariant: every event starting
  before the cursor is stored. Cursor = min bucket frontier (frontier =
  start of earliest held-back event, else now). 600s overlap re-read is a
  safety net; dedup eats repeats.
- Settled rule: held back if possibly the bucket's latest AND end ≥ now−120s
  (ties err toward holding back).
- Incremental poll advances the cursor atomically with the batch; explicit
  [start,end) (backfill) never touches the cursor. **Ticket 07: `frontier <
  end` means the chunk is incomplete — re-pull [frontier, end) later;
  `held_back` reports it.**
- `source_id = f"{bucket_id}/{event_id}"`; payload verbatim up to JSON
  round-trip (key order kept).
- Hygiene: titles/apps whitespace-collapsed, capped 2000; URLs
  control-char-stripped (consistent with urlsplit), capped 4096, http(s)-only
  domain extraction with www-strip; lone surrogates replaced; malformed
  events logged + skipped; negative durations zeroed (payload untouched).
- Mapping version seeded BEFORE first insert, never overwritten: "no meta
  row = no signals" stays true, and a stale recorded version remains visible
  as a mismatch (seed-after could mask a v1/v2 mix). Reviewer's atomicity
  concern judged less dangerous than the alternative; documented at the call
  site with tests.
- Cursor lag grows with the current window/AFK state length — expected, not
  a stall (ticket 05 status note).
- Live dry-run (scratch DB, deleted): first poll 5709 obs / 5627 signals /
  82 AFK without signals; second poll 0 inserted; domains sane.
- 120 tests green, ruff clean, POC unittest OK.
