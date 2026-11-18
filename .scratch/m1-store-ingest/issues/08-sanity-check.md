# 08 — Sanity check: everything, live

Type: task (HITL)
Status: resolved
Blocked by: 06, 07

## Task

End-to-end verification that M1 is actually done, against real data.

- Full test suite green; ruff clean.
- `ingest --watch` running against live ActivityWatch; `status` shows fresh
  cursors for window/AFK/Chrome.
- SQL eyeball with Brandon: `signals.app/domain/url/title` populated and
  sensible; `observations.payload` verbatim vs the AW API for sampled
  events.
- Cross-check: one full day's per-app foreground totals from `signals`
  (clipped + merged the same way) vs the POC's `/usage` for the same range —
  the correctness oracle for clipping/merge bugs. Investigate any
  discrepancy beyond AFK/settled-margin explanations.
- Walk the M1 checklist in `docs/DESIGN.md` §9 and tick every box.

## Acceptance

Every M1 checkbox ticked in DESIGN.md; discrepancies explained or fixed.
Resolving this ticket closes the map.

## Answer

Done (run by the orchestrator against live data, 2026-11-17). All checks
passed; zero discrepancies.

- Suite: 223 pytest green, ruff clean, POC unittest 12 green.
- Live pipeline: backfill stored 5,709 observations / 5,627 signals
  (2026-11-12 → now); re-run inserted 0; a follow-up `ingest` cycle inserted
  0 with the 3 current events correctly held back; `status` shows all three
  sources fresh with honest per-source "unobserved" gaps (aw-web gaps =
  browser not in use).
- Normalization eyeball: sampled aw-window rows have `app`+`title`, aw-web
  rows have `url`+`domain`+`title` (www stripped, e.g. `google.com`), 0
  window rows missing app, 0 web rows missing url, 0 AFK signal rows. Top
  apps/domains look right (Chrome, Warp, ChatGPT… / mail.google.com,
  docs.google.com…).
- Verbatim payload: a random stored observation compared equal
  (json-level) to AW's own `GET /events/{id}` for the same event.
- Rebuild determinism on real data: `rebuild-signals` twice → identical
  SHA-256 over all 5,627 ordered rows (54f8ae4c5085e9a9).
- **Oracle cross-check:** per-app foreground totals for 2026-11-16 (local
  day), computed from our `signals` with clip+merge, vs the POC Bridge's
  breakdown over the same range: all top 8 apps match to 0.1s exactly
  (loginwindow 63,479.7s, Chrome 11,265.2s, Claude 6,191.3s, …).
- DESIGN.md M1 checklist: all 8 boxes ticked. AGENTS.md updated to "M1
  complete" with the new commands and test matrix.

This closes the map: M1 is implemented, reviewed, tested, and verified live.
