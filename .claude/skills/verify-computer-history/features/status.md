# Status

`status` reports, without writing anything, the database, whether
ActivityWatch answers, each source's freshness, coverage gaps reported as
unobserved time, the capture agent's health and the row counts.

## Sub-features

- `status-missing` a database that does not exist yet reads `not created yet` and is not created.
- `status-sources` each source line shows observations, latest end and settled-until lag.
- `status-gaps` gaps of 5m or more are warnings of unobserved time, never idle.
- `status-agent` the capture agent section: last capture, alive, spool, today, paused.
- `status-aw-down` ActivityWatch unreachable reads `ActivityWatch: no`.

## How to get to it (user POV)

- `computer-history status`
- `computer-history status --spool-path <folder>` for another spool.

## Driving it with chv

Preconditions:

- A fresh run; `$C doctor` all `ok`.

- **Missing database.** Run `$C cli status`. Exit `0`; stdout has
  `(not created yet; run \`computer-history ingest\`)` and
  `ActivityWatch: yes (...; sources: aw-afk, aw-web, aw-window)`. Then
  `$C sql "SELECT 1"` refuses with `chv: no database at ... yet`: none was created.
- **Agent before any record.** Run `$C cli backfill` (a database with
  ActivityWatch rows only), `$C spool-seed --now`, then `$C cli status`.
  The section is one line plus the spool:
  `Capture agent: has not reported yet (no ax-text records stored)` and
  `spool 1 finished file waiting (oldest 0s), 0 in unreadable/`.
- **Agent alive.** Run `$C cli ingest`, then `$C cli status`. The
  `Capture agent:` block reads `last capture ... (Ns ago)`, `alive yes`, and
  `today 1 captures stored`.
- **Agent not alive.** Start a fresh run. Run `$C spool-seed` (fixture records
  dated 2026-11-18), `$C cli ingest`, `$C cli status`. The block reads
  `alive NO: no record since 2026-11-18 ..., although aw-afk shows you active since then`.
- **Sources and gaps.** The same output's `Sources:` block lists `aw-afk 4`,
  `aw-web 2`, `aw-window 17`, `ax-text 7` observations; `Coverage gaps` has
  `warning: no aw-web coverage from ... (16m ...)` and an
  `ax-text ... while you were active` line.
- **Rows.** The `Rows:` block's `observations` equals
  `$C sql "SELECT COUNT(*) FROM observations"`.
- **ActivityWatch down.** Run `$C cli status --aw-url http://127.0.0.1:9/api/0`
  (the later flag wins). Stdout has `ActivityWatch: no  (http://127.0.0.1:9/api/0)`;
  stderr has `!! ActivityWatch is UNREACHABLE at ...`.

## Gotchas

- `status` never migrates: on an outdated schema it prints a `note:` and stops.
- On a missing database `status` prints only the database and ActivityWatch
  lines; the agent section needs a database to exist.
- Gap lines depend on the clock; assert the phrases and durations, not times.
- `aw-web` is settled until now (no growing event), so its lag reads `0s`.
- `today` counts only stored records; a spooled record is not in it until ingested.
- Until some ax-text record is stored, the agent section is the one-line form
  even when the spool holds a fresh record.
