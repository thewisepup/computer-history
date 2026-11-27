# Backfill

`backfill` imports existing ActivityWatch history in 7-day chunks, oldest
first; `--dry-run` prints the plan and writes nothing, and a rerun adds
nothing.

## Sub-features

- `backfill-plan` the dry run lists each source's range and chunks and writes nothing.
- `backfill-run` the import stores history and sets ingest progress.
- `backfill-rerun` a second run inserts 0.
- `backfill-start` `--start` overrides where the plan begins.

## How to get to it (user POV)

- `computer-history backfill --dry-run`
- `computer-history backfill`
- `computer-history backfill --start <ISO date>` (and `--end <ISO date>`; dates without an offset are local time)

## Driving it with chv

Preconditions:

- A fresh run with no ingest yet; `$C doctor` all `ok`.

- **Plan.** Run `$C cli backfill --dry-run`. Exit `0`; stdout starts
  `Dry run: would backfill`, lists `aw-afk`, `aw-web`, `aw-window` each
  `(1 bucket): [<3 days ago, midnight>, <now>) up to now (no ingest progress yet), 1 chunk`,
  and ends `dry run: nothing written`.
- **Nothing written.** Run `$C cli status`. Still `not created yet`.
- **Import.** Run `$C cli backfill`. Exit `0`; per source a
  `done in` line (`aw-afk ... inserted 4, ... held back 1`,
  `aw-web ... inserted 2`, `aw-window ... inserted 17, ... held back 1`), a
  `note: ... had not settled yet (held back)` line for the two with a growing
  event, a `progress set: settled until ...` line, then `Backfill totals:`.
- **Stored.** Run `$C sql "SELECT source, settled_until FROM ingest_progress"`.
  One row each for `aw-afk`, `aw-web`, `aw-window`.
- **Ingest continues.** Run `$C cli ingest`. AW streams report `inserted 0`.
- **Rerun.** Run `$C cli backfill`. Every `done in` line reads `inserted 0`
  (`skipped 4`, `2`, `17`).
- **Start override.** Run `$C cli backfill --dry-run --start $(date -v-1d +%Y-%m-%d)`.
  Each range begins at yesterday `00:00` and runs `up to its settled-until time`;
  `aw-afk` and `aw-window` each add
  `warning: aw-watcher-..._<host> has events before <yesterday> 00:00 ...; they are NOT included and progress will not be set.`

## Gotchas

- The fake's buckets were created 3 days before launch; that is where the plan starts.
- A run that already ingested has progress, so backfill plans only up to it;
  start a fresh run for the plan-from-empty journey.
- `--dry-run` refuses an outdated schema rather than migrating it.
