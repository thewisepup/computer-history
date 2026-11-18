# 08 — Sanity check: everything, live

Type: task (HITL)
Status: open
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
