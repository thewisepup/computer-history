# Wayfinder map: Deepen ingest modules before M2

Label: wayfinder:map

## Destination

The four deepening candidates from the 2026-11-18 architecture review are
implemented, tested and reviewed, so M2 (AX-text JSONL spool, `(file, offset)`
cursor) ships as one new source adapter plus one projector, with no edits to
orchestration, cursor rules, status, or the CLI.

## Notes

- **Execution override:** each ticket is an incremental, verifiable build
  step; resolving it means code written, tests green, both reviews done.
- **Review requirement:** every ticket gets two separate review passes by
  fresh contexts: `/code-review medium` (correctness) and the
  `standards-reviewer` agent. Fix round goes back to the implementer.
- Tickets run strictly in order (they share `cli/`, `sources/`, `store/`).
- One commit per resolved ticket; plain subject, no ticket prefix.
- Settled decisions (Brandon, 2026-11-18): implement candidates 1–4 of the
  review (runner, progress, projection, store open). Candidates 5 (datetimes
  only across the store interface) and 6 (per-source coverage) are out of
  scope. Ticket order chosen for dependency: store open → progress → runner
  → projection.
- Rules every ticket keeps: AGENTS.md "Rules every change keeps",
  CODING_STANDARDS.md (near-zero comments, layering, CLI holds no business
  logic), DESIGN.md package layout + `computer_history/cli/README.md` updated
  in the same commit as any layout or command-output change.

## Decisions so far

<!-- one line per closed ticket: [title](issues/NN-slug.md): gist -->
- [01 — Open the store by purpose](issues/01-store-open.md): `store.open_store(path, Purpose.READ|WRITE|WRITE_EXISTING) -> OpenedStore` reports READY/MISSING/OUTDATED/NEWER/BUSY/UNREADABLE; no command reads a mismatched schema; newer-schema traceback fixed; CLI only maps states to messages (`cli/db.py`); backfill planning moved to `sources.plan_all_backfills`.
