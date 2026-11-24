# Status

`status` reports, without writing anything, the database, whether
ActivityWatch answers, each source's freshness, coverage gaps reported as
unobserved time, the capture agent's health and the row counts.

## Sub-features

- `status-missing` a database that does not exist yet reads `not created yet` and is not created.
- `status-sources` each source line shows observations, latest end and settled-until lag.
- `status-gaps` gaps of 5m or more are warnings of unobserved time, never idle.
- `status-checks` the `Watchdog checks` block: one line per check, in the watchdog's words.
- `status-agent` the capture agent section: last capture, spool, today, paused.
- `status-screenshots` the screenshots section: last kept, counts by status, disk, the no-permission warning.
- `status-aw-down` ActivityWatch unreachable opens with a banner and its check reads `unreachable`.

## How to get to it (user POV)

- `computer-history status`
- `computer-history status --spool-path <folder>` for another spool.

## Driving it with chv

Preconditions:

- A fresh run; `$C doctor` all `ok`.

- **Missing database.** Run `$C cli status`. Exit `0`; stdout has
  `(not created yet; run \`computer-history ingest\`)` and
  `ActivityWatch: http://... (sources: aw-afk, aw-web, aw-window)`. Then
  `$C sql "SELECT 1"` refuses with `chv: no database at ... yet`: none was created.
- **Agent before any record.** Run `$C cli backfill` (a database with
  ActivityWatch rows only), `$C spool-seed --now`, then `$C cli status`.
  The section is one line plus the spool:
  `Capture agent: has not reported yet (no ax-text records stored)` and
  `spool 1 finished file waiting (oldest 0s), 0 in unreadable/`.
- **Agent alive.** Run `$C cli ingest`, then `$C cli status`. The
  `Watchdog checks` block reads `capture agent  ok: recording, last seen ...`,
  and the `Capture agent:` block `last capture ... (Ns ago)` and
  `today 1 captures stored`.
- **Agent not alive.** Start a fresh run. Run `$C spool-seed` (fixture records
  dated 2026-11-18), `$C cli ingest`, `$C cli status`. The checks read
  `capture agent  PROBLEM: silent while you were active, last seen 2026-11-18 ...`.
- **Sources and gaps.** The same output's `Sources:` block lists `aw-afk 4`,
  `aw-web 2`, `aw-window 17`, `ax-text 7` observations; `Coverage gaps` has
  `warning: no aw-web coverage from ... (16m ...)` and an
  `ax-text ... while you were active` line.
- **Screenshots.** With ActivityWatch rows only, `Screenshots: none stored
  yet (no screenshot records)`. After the fixture ingest above: `last kept
  2026-11-18 ...`, `all stored 1 kept, 1 duplicate, 1 secure-field, 1
  no-permission, 1 failed`, `disk 179.1 KB in total, 0 B today`, and the
  `warning: Screen Recording permission is missing since 2026-11-18 ...` line,
  since the fixture's newest screenshot record is `no-permission`. Coverage
  reads `screenshot: not checked (coverage is judged from ax-text records)`.
- **Rows.** The `Rows:` block's `observations` equals
  `$C sql "SELECT COUNT(*) FROM observations"`.
- **ActivityWatch down.** Run `$C cli status --aw-url http://127.0.0.1:9/api/0`
  (the later flag wins). Stdout opens with `!! ActivityWatch is UNREACHABLE at
  http://127.0.0.1:9/api/0: ...`, and the checks read `ActivityWatch  cannot tell:
  unreachable, since ...` with the connection error.

## Gotchas

- `status` never migrates: on an outdated schema it prints a `note:` and stops.
- On a missing database `status` prints only the database, ActivityWatch and
  Ingest lines and the checks; the agent section needs a database to exist.
- Gap lines depend on the clock; assert the phrases and durations, not times.
- `aw-web` is settled until now (no growing event), so its lag reads `0s`.
- `today` counts only stored records; a spooled record is not in it until ingested.
- Until some ax-text record is stored, the agent section is the one-line form
  even when the spool holds a fresh record.
