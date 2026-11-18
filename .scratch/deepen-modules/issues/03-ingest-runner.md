# 03 — One ingest runner behind a source adapter seam

Type: task
Status: open
Blocked by: 02

## Problem

Three loops wrap `ingest_source`: `run_cycle`/`watch` in `cli/ingest.py`
(production poll + error policy: AWError / OperationalError end the cycle,
earlier sources stay committed), `ingest_all` (only tests call it, no error
policy), and `run_backfill` (chunk loop + incomplete rule + progress init),
with `cli/backfill._backfill_one` re-deriving "incomplete" and why the cursor
was or wasn't set. `ingest_source` hides a mode flag in optional
`start`/`end`. Tests reach the real loops only by monkeypatching
`cli_ingest.ingest_source`, `cli_ingest.AWClient`, `backfill_module.ingest_source`.

## Task

Introduce a source adapter seam and one source-agnostic runner in
`sources/`:
- The adapter Protocol is the minimal set of operations a source needs:
  name its streams (AW: aw-window/aw-afk/aw-web), pull observations after a
  progress position, pull an explicit range, and report the new position /
  settled_until / held-back count. Its failure is one exception family the
  runner understands as "source unavailable" (AWError joins it). The AW
  adapter implements it; backfill-planning facts it needs (history start,
  earlier-history probe) become adapter operations if that is what keeps the
  runner source-agnostic.
- The runner owns: polling every stream of every adapter (incremental
  mode), ingesting a planned range in chunks (backfill mode, including the
  incomplete rule and the set-if-none progress from ticket 02), the
  per-stream error policy, and returning structured outcomes. The watch loop
  (interval, injected sleep/clock) lives here too; the CLI only formats and
  logs its reports.
- The CLI keeps constructing clients/adapters and connections (layering rule
  in `test_standards.py`) and passes them in. CLI modules end up as parse →
  one call → format → exit code.
- Delete `ingest_all` and the duplicated incomplete/cursor reasoning in
  `cli/backfill.py`. Explicit modes instead of a mode inferred from optional
  args.

## Acceptance

- A small in-memory fake adapter in tests (second adapter makes the seam
  real) drives the runner: source-unavailable mid-cycle keeps earlier streams
  committed and reports the failed stream; DB lock likewise; backfill chunks
  with an incomplete chunk report it once and set progress correctly.
- Existing AW behaviour unchanged end to end (fake_aw-based tests still pass,
  adjusted to the new entry points). No test monkeypatches `ingest_source`
  or module attributes to reach the loops.
- DESIGN.md package layout, package `__init__` flow diagrams,
  `cli/README.md` updated. Full suite + ruff green.
