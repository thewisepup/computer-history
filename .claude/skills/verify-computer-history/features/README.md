# computer-history verification map

The maintained source for verifying the `computer-history` CLI. Read this
index, then the feature file for what you are verifying.

## Baseline preconditions

- A fresh run from `eval "$($C up)"`, with
  `C=.claude/skills/verify-computer-history/scripts/chv`, run from the repo root.
- `$C doctor` reports every line `ok`.
- The run's database does not exist until the first `ingest` or `backfill`.
- The fake ActivityWatch holds the seed described in `../SKILL.md` (Launch).
- The spool is empty until a `spool-seed`.

## Driving conventions

- Drive every command through `$C cli`; never call `.venv/bin/computer-history`
  directly, which would default to the live database.
- Treat command lines as literal; the quoted output strings are the CLI's own.
- A feature that needs a fresh database starts its own run (`$C down`, then
  `eval "$($C up)"`).

## Proof and skip reporting

- Proof is the numbered transcripts in `output/verify/<CHV_RUN>/`, each with
  command, exit code, stdout and stderr.
- Every mutation is followed by a read-only view (`$C sql`, `$C spool-ls`,
  or `$C cli status`).
- Report each entry point by sub-feature ID with its transcript file names.
- An entry point that could not be driven is reported with the command tried
  and the unmet precondition, never as verified through another path.

## Feature entry contract

Each feature file has an H1 title, a paragraph on the user-visible behavior,
then `Sub-features`, `How to get to it (user POV)`, `Driving it with chv`
(starting with `Preconditions:`), and `Gotchas`.

## Features

- [Ingest](./ingest.md): one poll and `--watch` across ActivityWatch and the
  spool; idempotence, held-back events, rejected spool lines.
- [Status](./status.md): database, sources, coverage gaps, capture agent and
  row counts; read-only on a missing database.
- [Backfill](./backfill.md): dry-run plan and the chunked history import.
- [Rebuild signals](./rebuild-signals.md): re-projecting the derived layer
  from stored observations.
