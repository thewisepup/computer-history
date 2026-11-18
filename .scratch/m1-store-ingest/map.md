# Wayfinder map: M1 — Package + store + AW ingest

Label: wayfinder:map

## Destination

Milestone 1 of `docs/DESIGN.md` fully implemented and verified: new
`computer_history` package in this repo, §3 schema created via numbered SQL
migrations, ActivityWatch ingest (window/AFK/Chrome, settled events only,
idempotent), `ingest` / `status` / `rebuild-signals` / `backfill` CLI, all
tests green, and a live sanity check against real ActivityWatch data
cross-checked with the POC's `/usage` numbers.

## Notes

- **Execution override:** this map carries execution, not just decisions.
  Each ticket is an incremental, verifiable build step; resolving a ticket
  means the code is written, tested, and reviewed.
- **Review requirement:** every implementation ticket gets a code-review pass
  (fresh reviewer context, not the implementer) before it is resolved.
- One ticket per agent session; tickets 05 and 06 are independent of each
  other and may run in parallel once 04 is resolved.
- Settled decisions (Brandon, 2026-11-17):
  - Full M1 is the destination, not just skeleton + schema.
  - Same repo, one `pyproject.toml`; POC (`history.py` etc.) untouched and
    runnable until M6. Repo is already a git repo (AGENTS.md is stale on this).
  - SQL migrations via SQLite `user_version` + numbered files; migration 001
    carries the complete §3 schema (all layers) + `block_evidence_v`.
  - DB defaults to `~/Library/Application Support/ComputerHistory/history.db`;
    overridable via `--db-path` flag and `COMPUTER_HISTORY_DB` env var; tests
    use tmp-dir file databases (never the prod path, never `:memory:`).
  - pytest + ruff for the new package. Agent has license to override/remove
    for code quality.
  - Settled-events stability margin: 120s (2× the 60s poll interval) —
    default chosen where the design doc is silent.
  - M1 runner is `ingest --watch` (long-lived loop); no FastAPI server in M1.
- Source of truth for scope and schema: `docs/DESIGN.md` §2–§4, §9 (M1).

## Decisions so far

<!-- one line per closed ticket: [title](issues/NN-slug.md): gist -->

## Not yet specified

(none — M1 is fully ticketed; everything beyond it is out of scope)

## Out of scope

- M2–M9 of the design doc: Swift capture agent, screenshots/OCR,
  LaunchAgents, classification, MCP/REST interfaces, weekly review, React UI,
  early adopters.
- Any FastAPI `serve` command (arrives with the API milestones).
- Writes to layer-2/3 tables (`projects`, `blocks`, `reviews`, …): their
  schema ships in migration 001, but nothing populates them in M1.
