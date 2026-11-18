# 04 — Sources own signal projection

Type: task
Status: open
Blocked by: 03

## Problem

`project_signal` (AW only; raises ValueError for any other source) is
called at ingest by `aw/pull._observation` and, at rebuild, imported and
chosen by `cli/rebuild.py` and passed into `store.rebuild_signals`, which
counts every raise as a "malformed payload" and aborts above 50%. After M2,
`ax-text` rows would either all be dropped while the rebuild commits
("skipped N malformed"), or block every rebuild. The signal row shape
(`INSERT_SIGNAL`, `signal_params`) is defined in `observations.py` and also
written by `signals.py`.

## Task

- Each adapter supplies its projector; one projection module in `sources/`
  routes an observation to its source's projector. Ingest (via the runner)
  and rebuild use the same routing, so a rebuild reproduces ingest's
  signals exactly.
- An observation from a source no adapter claims is a distinct, loud error
  — never counted as a malformed payload. The store defines the error type
  if it must recognise it (store can't import sources).
- The CLI no longer chooses a projector: `rebuild-signals` calls one
  function that wires routing into the store's rebuild.
- One store module owns the signal row shape and writes; the other imports
  it.
- Stateful projection (AX "dedup against previous capture") is out of scope;
  don't design it in, just don't make it harder (e.g. keep the projector
  call a single seam).

## Acceptance

- Test: ingest via the runner, rebuild, signals identical row-for-row.
- Test: an observation with an unclaimed source makes rebuild fail loudly
  with a clear message and leaves signals unchanged; it is not reported as
  malformed.
- Test: a fake adapter's projector is used by both ingest and rebuild.
- No test monkeypatches `cli_rebuild.project_signal`. DESIGN.md layout,
  flow diagrams, `cli/README.md` updated. Full suite + ruff green.
