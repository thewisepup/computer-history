# Status

`status` reports, without writing anything, the database, whether
ActivityWatch answers, each source's freshness, coverage gaps reported as
unobserved time, the capture agent's health and the row counts, then the
database's backups and the stable install's state.

## Sub-features

- `status-missing` a database that does not exist yet reads `not created yet` and is not created.
- `status-sources` each source line shows observations, latest end and settled-until lag.
- `status-gaps` gaps of 5m or more are warnings of unobserved time, never idle.
- `status-checks` the `Watchdog checks` block: one line each for `capture agent`, `ActivityWatch` and `backend`, in the watchdog's words.
- `status-agent` the capture agent section: last capture, spool, today, paused, app agreement with aw-window.
- `status-screenshots` the screenshots section: last kept, counts by status, disk, the no-permission warning.
- `status-aw-down` ActivityWatch unreachable opens with a banner and its check reads `unreachable`.
- `status-stable` the `Backups`, `Stable install`, `Stable install's LaunchAgents` and `Stable watchdog` sections.

## How to get to it (user POV)

- `computer-history status`
- `computer-history status --spool-path <folder>` for another spool.

## Driving it with chv

Preconditions:

- A fresh run; `$C doctor` all `ok`.

- **Missing database.** Run `$C cli status`. Exit `0`; stdout opens
  `Profile dev (branch ... at ...), database ...`, then has
  `(not created yet; run \`computer-history ingest\`)`,
  `ActivityWatch: http://... (sources: aw-afk, aw-web, aw-window)` and
  `Ingest:        no \`ingest --watch\` has reported yet`; the checks read
  `capture agent  cannot tell: nothing recorded yet`,
  `ActivityWatch  ok: recording, last seen ...` and
  `backend        cannot tell: silent, but aw-afk does not show you active`. Then
  `$C sql "SELECT 1"` refuses with `chv: no database at ... yet`: none was created.
- **Agent before any record.** Run `$C cli backfill` (a database with
  ActivityWatch rows only), `$C spool-seed --now`, then `$C cli status`.
  The section is one line plus the spool:
  `Capture agent: has not reported yet (no ax-text records stored)` and
  `spool 1 finished file waiting (oldest 0s), 0 in unreadable/`. The checks
  already read `capture agent  ok: recording`: they judge the spooled record too.
- **Agent alive.** Run `$C cli ingest`, then `$C cli status`. The
  `Watchdog checks` block reads `capture agent  ok: recording, last seen ...`,
  `ActivityWatch  ok: recording, last seen ...` and
  `backend        PROBLEM: silent while you were active` (no watch has reported;
  the Watch step in [ingest](./ingest.md) turns it `ok`). The `Capture agent:`
  block has `last capture ... (Ns ago)`, `today 1 captures stored` and
  `app agreement 1 of 1 captures match aw-window (0 differ, 0 without aw-window data)`.
- **Agent not alive.** Start a fresh run. Run `$C spool-seed` (fixture records
  dated 2026-11-18), `$C cli ingest`, `$C cli status`. The checks read
  `capture agent  PROBLEM: silent while you were active, last seen 2026-11-18 ...`.
- **Sources and gaps.** The same output's `Sources:` block lists `aw-afk 4`,
  `aw-web 2`, `aw-window 17`, `ax-text 9`, `screenshot 5` observations; `Coverage gaps` has
  `warning: no aw-web coverage from ... (16m ...)` and an
  `ax-text ... while you were active` line.
- **Screenshots.** With ActivityWatch rows only, `Screenshots: none stored
  yet (no screenshot records)`. After the fixture ingest above: `last kept
  2026-11-18 ...`, `all stored 1 kept, 1 duplicate, 1 secure-field, 1
  no-permission, 1 failed`, `disk 179.1 KB in total, 0 B today`, and
  `permission    last recorded missing 2026-11-18 ..., missing since 2026-11-18 ...; no screenshot record since says whether it is held`,
  since the fixture's newest screenshot record is a days-old `no-permission`
  (the `warning:` form needs one from the last 5 minutes). Coverage
  reads `screenshot: not checked (coverage is judged from ax-text records)`.
- **Rows.** The `Rows:` block's `observations` equals
  `$C sql "SELECT COUNT(*) FROM observations"`.
- **ActivityWatch down.** Run `$C cli status --aw-url http://127.0.0.1:9/api/0`
  (the later flag wins). After the `Profile` line, stdout has `!! ActivityWatch
  is UNREACHABLE at http://127.0.0.1:9/api/0: nothing new can be ingested.`, the
  `ActivityWatch:` line has no sources list, and the checks read
  `ActivityWatch  cannot tell: unreachable, since ...` with the connection error.
- **Stable sections.** Every output ends with `Backups:` (`none yet (the daily
  backup takes one a day into <run folder>/backups/daily)` until a
  [backup](./backup.md)), `Stable install:` (`this run      dev`, then the
  stable install's versions), `Stable install's LaunchAgents:` and
  `Stable watchdog:`.

## Gotchas

- `status` never migrates: on an outdated schema it prints a `note:` and stops.
- On a missing database `status` prints the database, ActivityWatch and
  Ingest lines, the checks and the stable sections; Sources through Rows need
  a database to exist.
- The stable sections are read, never written, from the live install on this
  machine (its versions, LaunchAgents and watchdog state); assert their
  headings and `this run      dev`, not their values.
- An `ok` on `ActivityWatch` needs buckets named for this host; the fake
  names them `<watcher>_<hostname>`, as ActivityWatch does.
- A check whose subject was seen in the last instant can read `0s ahead of now`.
- Gap lines depend on the clock; assert the phrases and durations, not times.
- `aw-web` is settled until now (no growing event), so its lag reads `0s`.
- `today` counts only stored records; a spooled record is not in it until ingested.
- Until some ax-text record is stored, the agent section is the one-line form
  even when the spool holds a fresh record.
