# 04 — Sources own signal projection

Type: task
Status: resolved
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

## Answer

**Built.** Signals are now always derived inside the store from the stored
payload, through one projector the caller passes; adapters only pull raw
observations and name their projectors.

```python
# sources/contract.py
StreamProjector = Callable[[str], Signal | None]          # stored payload -> signal
class Projecting(Protocol):
    projectors: Mapping[str, StreamProjector]            # every stream it can ever feed
class Source(Projecting, Protocol): ...                  # streams + pull_after, as before

# sources/projection.py
KNOWN_SOURCES: tuple[Projecting, ...] = (ActivityWatch,)
projector_for(sources) -> Projector                      # routes by observation source
reproject_signals(conn, *, allow_shrink=False, sources=KNOWN_SOURCES) -> RebuildResult

# store
Projector = Callable[[str, str], Signal | None]          # (source, payload)
class UnclaimedSource(LookupError)                       # .source
insert_observations(conn, observations, *, project, progress=None, now=None)
rebuild_signals(conn, project, *, batch_size, allow_shrink)
RebuildAborted(..., unclaimed: str | None)               # new field
```

- `Observation` lost its `signal` field; `pull.py` no longer projects.
- ActivityWatch: `normalize.PROJECTORS` (aw-window, aw-afk, aw-web, each a
  `partial` of the unchanged `project_signal`), set as the class attribute
  `ActivityWatch.projectors`.
- `poll` builds `projector_for(sources)` once per cycle, `run_backfill`
  builds `projector_for([source])`; both pass it through `commit_pull(...,
  project=)` to `insert_observations`.
- `store/signals.py` owns the signal row shape and writes (`Signal`,
  `SignalRow`, `write_signals`, private `_INSERT_SIGNAL`);
  `observations.py` imports them. `INSERT_SIGNAL` and `signal_params` are
  gone.
- `rebuild-signals` calls `reproject_signals(conn, allow_shrink=)`; the CLI
  no longer picks a projector.

**Decisions.**

- *The observation write projects, not the commit step.* `insert_observations`
  calls `project(source, payload)` on each newly inserted row, using the
  payload text it just stored; rebuild calls the same projector on every row
  in id order. So ingest and rebuild give the projector exactly the same
  input in the same order, and nobody can hand the store a signal that
  doesn't match its payload. Re-read duplicates (AW's 600s rewind, idempotent
  backfill) are no longer projected at all, which also keeps the seam safe
  for a later stateful AX projector. The cost: `project` is a required
  keyword on `insert_observations`, so 60-odd test calls gained
  `project=...` (via the new `tests/projectors.py`: `AW`, `no_signal`,
  `payload_fields`). I made it required because a default of "no signals"
  would let a new caller drop signals without noticing.
- *Projectors are static, per stream, and live on the adapter class.*
  Rebuild has no AW client and must still project rows from streams with no
  buckets right now (e.g. a removed web watcher). `streams()` is dynamic, so
  `projectors` is separate and lists every stream the adapter can ever feed.
  `Projecting` is its own small Protocol so a class (no client) satisfies it;
  `Source` extends it.
- *Ingest routes over the adapters it polls; rebuild over `KNOWN_SOURCES`.*
  Both go through `projector_for`, and the AW projectors are the same
  objects either way. If a future adapter is polled but left out of
  `KNOWN_SOURCES`, rebuild fails loudly on its rows (below) instead of
  dropping them. `projector_for` refuses two adapters that claim one stream
  with different projectors ("stream 'a' is fed by more than one source", the
  message poll already used), before anything is read; the same adapter
  listed twice counts as one claim.
- *Unclaimed source.* The router raises the store's `UnclaimedSource`.
  At ingest it rolls back that stream's batch and progress and propagates out
  of `poll` (an adapter emitting a stream it doesn't project is a programming
  error, like other non-source errors today). At rebuild it is caught before
  the malformed handler and becomes `RebuildAborted(unclaimed=source,
  failed=0)`, so the transaction rolls back and signals are unchanged. The
  message gives the source, how many stored rows it has and the first id;
  the CLI adds one hint line:
  `rebuild-signals aborted: no source adapter projects 'ax-text', the source of 12 stored observations (first id: 7); rolled back, signals unchanged`
  / `  this computer-history has no adapter for that source; rebuild with the version that ingested it`.
  It never appears as "malformed" or under "first failing observation ids".
- *Projection errors at ingest still propagate*, as before (AW's projector
  never raises on a payload it serialised itself). So every stored row
  projected cleanly at ingest, and only a changed projector can make rebuild
  skip rows.
- `Signal` moved from `observations.py` to `signals.py` (the row shape's
  owner); `store` still re-exports it, so no caller changed.

**Tests.** New `tests/test_projection.py` (10): known sources cover every AW
stream; unclaimed raises its own error; conflicting claims refused; same
adapter twice allowed; **ingest via the runner (poll of AW + fake spool, and a
fake backfill) then `reproject_signals` gives identical rows**; **a fake
adapter's projector serves both ingest and rebuild** (it records every
payload: once per stored row at ingest, again at rebuild); duplicates aren't
projected; an adapter emitting an unprojected stream fails ingest and stores
nothing for it; **an unclaimed source aborts rebuild with signals unchanged,
`failed == 0`, no "malformed"**, both through the function and the CLI.
`test_store_api`: unclaimed source rolls back the batch and its progress.
`test_cli_rebuild_signals_allow_shrink` no longer monkeypatches
`cli_rebuild.project_signal`: it stores signals for AFK rows (which the
current mapping drops) and lets the real rebuild shrink. `FakeSource` gained
`projectors` + `projected`. 588 pytest, ruff clean, POC unittest 12 OK.

**Docs.** DESIGN.md: layout (store/observations, store/signals,
sources/projection, activitywatch normalize), §3.2 (signals projected from
the stored payload through the shared routing), §4 adapter contract
(projectors, routing, `reproject_signals`, `UnclaimedSource`).
`sources/` and `activitywatch/` diagrams, `store` docstring, and
`cli/README.md` (rebuild-signals wording + the unclaimed abort output).

**Review fixes.**

- *An unprojectable stream no longer kills ingest.* New
  `FailureKind.ADAPTER`: `failure_of` maps `UnclaimedSource` and the new
  `StrayObservation` to it. `poll` catches them per stream, so that stream's
  batch and progress roll back, it is reported in `CycleSummary.failures`,
  and the source's other streams and the other sources still run. `watch`
  logs it like any failed cycle and keeps polling. One-shot `ingest` prints
  `error on <stream>: <message>` (no busy hint) and exits 1. `run_backfill`
  stops on either and reports it (`backfill stopped: <message>`).
- *Unclaimed beats malformed at rebuild.* `rebuild_signals` takes
  `claimed=`, and when it's given, checks every distinct stored source
  against it before wiping or projecting anything. So an early burst of
  malformed rows can't trip the malformed-ratio abort first.
  `reproject_signals` passes the routing's claims. The in-scan catch stays
  for callers that pass no claims. The count and first id come from SQL.
- *Commit refuses stray observations.* `commit_pull` raises
  `StrayObservation` ("a pull of 'x' returned an observation from 'y'")
  before writing, if any observation's source isn't the stream being
  committed.
- Docstrings trimmed (`rebuild_signals`, `Projecting`). The formatting-only
  changes in `test_rebuild.py` and `test_progress.py` are reverted.
- *Not done (optional):* building the routing once per `watch` would add a
  `poll` parameter for no gain, since conflicts already surface on the first
  cycle, which runs at startup. `_claim` (streams listed this cycle) and the
  routing's conflict check (static claims; the same adapter twice is allowed)
  catch different things, so both stay.
- Tests (593 pytest, ruff clean, POC unittest OK): poll reports an
  unprojected stream and goes on with later streams and another source;
  stray observation from the fake source (nothing of that batch stored, no
  progress); backfill stops at a stray; watch logs the failure each cycle and
  keeps ingesting; CLI ingest prints the message and exits 1 with the other
  AW streams stored; early malformed rows plus a later unclaimed source abort
  as unclaimed (this test fails without the up-front check).
