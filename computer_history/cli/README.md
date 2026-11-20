# computer-history CLI

The command line for the local activity store: it ingests settled
ActivityWatch events and the capture agent's spool into SQLite and reports on
what is stored. All business logic lives in `sources/` and `store/`; this
package only parses arguments, builds the clients, source adapters and
connection, calls one function, and formats the result.

```
app.py         parser + dispatch: one entry per command
  |
  +-- ingest.py    one poll, or the --watch loop, through the ingest runner
  |                (ActivityWatch and the capture spool in one loop)
  +-- status.py    freshness, coverage gaps, the capture agent, screenshots, row counts
  +-- rebuild.py   rebuild-signals
  +-- backfill.py  plan, then ingest history chunk by chunk through the runner
        |
db.py and sources.py (unusable database / source messages),
formatting.py (durations, times, sizes)
```

Run it as `.venv/bin/computer-history`, or bare `computer-history` with the
venv activated (or aliased).

## ingest — the everyday command

```bash
computer-history ingest            # one poll: catch up from where the last one stopped
computer-history ingest --watch    # poll every 60s until Ctrl-C
```

```
Ingested from http://127.0.0.1:5600/api/0 and .../ComputerHistory/spool into .../ComputerHistory/history.db
  aw-afk     inserted      5  skipped      0  held back   1
  aw-web     inserted     62  skipped      1  held back   0
  aw-window  inserted    271  skipped      1  held back   1
  ax-text    inserted    412  skipped      0  held back   0  rejected 1
  screenshot inserted    410  skipped      0  held back   0
```

`inserted` is new rows, `skipped` is rows already stored (re-reads are
harmless), `held back` is ActivityWatch events still growing — they land on a
later poll. Re-running always inserts 0 for data it already has. `--watch` is
the long-running collector: one log line per cycle, survives ActivityWatch
outages and locked databases. A stream whose observations no adapter can
project is reported (`error on aw-window: no source adapter projects
observations from 'aw-window'`, exit 1) while the other streams are still
ingested.

`ax-text` and `screenshot` are the capture agent's spool, read in the same
poll. Each stream stores its own records from each finished `*.jsonl` file in
one commit, oldest first; the file is deleted once both streams have stored
it. The agent's `open.part` and `agent.lock` are never touched. A stream's
`rejected` counts lines of its own kinds that are not usable records (failing
validation, or an unknown format version); a line whose kind cannot be read
(not JSON, or a kind this backend does not know) belongs to neither stream and
is counted in the warning when the file is set aside. Unusable lines are skipped
and logged, and the rest of the file is stored. A file with any unusable line
is moved into `spool/unreadable/` instead of being deleted, once both streams
stored its usable lines. A file one stream cannot read is left for that stream
to retry on the next poll; only a file neither stream can read is moved aside.
A file that cannot be removed is reported as `error on the spool` and not read
again until the next `ingest` run. A missing
spool folder is nothing to ingest. ActivityWatch being down does not stop the
spool, and the reverse: the other source's rows are stored, and the run exits
1.

## status — is everything healthy?

```bash
computer-history status
computer-history status --spool-path /tmp/spool   # or $COMPUTER_HISTORY_SPOOL
```

```
Database:      .../ComputerHistory/history.db (5.2 MB, schema v5)
ActivityWatch: yes (http://127.0.0.1:5600/api/0; sources: aw-afk, aw-web, aw-window)

Sources:
  aw-window     3,451 observations  latest end 2026-11-18 10:10  settled until 2026-11-18 10:10 (5s behind now)
  ax-text         812 observations  latest end 2026-11-18 10:09  settled until 2026-11-18 10:09 (1m 10s behind now)
  ...
Coverage gaps (unobserved: nothing recorded) of 5m or more ...
  warning: no aw-web coverage from 2026-11-17 10:45 to 2026-11-17 12:25 (1h 39m)
  ax-text from 2026-11-17 10:09 to 2026-11-18 10:09 (unobserved: aw-afk shows you active, no record within 1m, not paused):
  warning: no ax-text coverage from 2026-11-18 08:02 to 2026-11-18 08:40 (38m), while you were active
  warning: no ax-text coverage from 2026-11-18 09:15 to 2026-11-18 09:27 (12m), cannot be judged: no aw-afk data
  screenshot: not checked (coverage is judged from ax-text records)

Capture agent:
  last capture  2026-11-18 10:09 (40s ago)
  alive         yes (last record 2026-11-18 10:10 (12s ago))
  spool         2 finished files waiting (oldest 1m 30s), 0 in unreadable/  (.../ComputerHistory/spool)
  today         812 captures stored, 14 excluded, 3 cut off, 1 timed out
  paused        no
  app agreement 1,602 of 1,615 captures match aw-window (13 differ, 41 without aw-window data)
                5 x Discord -> Google Chrome
                3 x Google Chrome -> Discord
                2 x Zoom -> Discord

Screenshots:
  last kept     2026-11-18 10:09 (45s ago), Cursor, screenshots/2026-11-18/6f1c2a52-8d0e-4b7a-9c3e-1a2b3c4d5e11.jpg
  today         402 kept, 377 duplicate, 6 secure-field, 0 no-permission, 1 failed
  all stored    6,904 kept, 7,311 duplicate, 85 secure-field, 12 no-permission, 9 failed
  disk          1.1 GB in total, 71.2 MB today (from kept records)

Rows:
  ...
```

Read-only: never creates, migrates or writes, and never changes the spool.
Gaps are reported as unobserved time, never assumed idle, and are checked up
to each source's settled-until time. Small lag is normal — an ActivityWatch
source is settled only up to the start of its current, still-growing event. A
source whose progress has no settled time shows `settled until - (progress
moved 30s ago)` instead.

`ax-text` captures are instants, so its gaps follow their own rule. A record
of any kind explains the minute on either side of it (twice the agent's 30s
heartbeat), and a pause explains the time until the next record. A stretch of
5m or more is unobserved when `aw-afk` shows you active and nothing explains
it; where `aw-afk` has no data and nothing explains it, the stretch *cannot be
judged*, never idle or active. The range ends at the last stored record while
the spool still holds records (finished files or a non-empty `open.part`),
otherwise now. `aw-afk` includes the newest AFK event from ActivityWatch, when
it is reachable, even before it is stored.

The capture agent section:

- **last capture**: the newest capture, stored or still in the spool
  (excluded and pause records are not captures).
- **alive**: `yes` when the newest record, stored or still in the spool, is
  at most 5 minutes old; `NO` when `aw-afk` shows you active for over a minute
  since it; `paused` while capture is paused; otherwise `cannot tell`.
- **spool**: finished `*.jsonl` files waiting to be ingested and how long the
  oldest has waited, then the files set aside in `unreadable/`. `open.part`
  and `agent.lock` are not counted. The spool path resolves as for `ingest`.
- **today**: the stored captures and excluded records since local midnight,
  and how many of those captures were cut off or timed out. Records still in
  the spool count once ingested.
- **paused**: `yes, since ...` when the newest record, stored or still in the
  spool, is `paused`: a `resumed`, a capture or an excluded record ends a
  pause.
- **app agreement**: each stored capture in the `ax-text` coverage range,
  checked against the app `aw-window` shows in front at its capture time. A
  capture matches when an `aw-window` span within 2s of it (the window
  watcher polls once a second) names the same app, ignoring case; otherwise
  it differs from the nearest such span. A capture with no `aw-window` span
  within 2s is counted apart, never as a match. When no capture can be
  judged, the line reads `cannot be judged: no aw-window data from this
  machine`, or `... near any capture` when there are spans but none within
  2s of a capture. The three most common differing `captured -> aw-window`
  pairs follow. Only app names are shown, never titles or text. Only this
  machine's window buckets count, the ones ActivityWatch names
  `<watcher>_<this hostname>`, so a bucket synced from another machine is
  ignored. `aw-window` includes the newest window event from ActivityWatch,
  when it is reachable, even before it is stored.

Before the agent has stored anything, the section is one line plus the spool:

```
Capture agent: has not reported yet (no ax-text records stored)
  spool         3 finished files waiting (oldest 2m 30s), 0 in unreadable/  (.../ComputerHistory/spool)
```

The screenshots section reads only stored `screenshot` records, never the
screenshots folder, through an index on their status, capture time and image
size, so it stays quick at months of records. Every stored record counts, by
its own capture time, including one dated after now when the agent's clock
runs ahead:

- **last kept**: the newest `kept` record, its app and the image path it
  names (relative to the data folder).
- **today** and **all stored**: records by status, since local midnight (the
  midnight's own offset, so a daylight saving changeover day starts on time)
  and in total. Records still in the spool count once ingested.
- **disk**: the `image_bytes` of the `kept` records, in total and today. An
  image left without a record is not counted.
- **warning**: printed when a `no-permission` record is newer than every
  `kept` and `duplicate` record, with the time of the first `no-permission`
  record after the last screenshot taken. `secure-field` and `failed` records
  neither raise nor clear it.

After the end-to-end check's scripted session, whose last two captures lost
the grant (real output):

```
Screenshots:
  last kept     2026-11-18 01:05 (1d 19h ago), Calculator, screenshots/2026-11-18/eb706daf-4138-4be3-aa0d-13ba3f4f63ea.jpg
  today         0 kept, 0 duplicate, 0 secure-field, 0 no-permission, 0 failed
  all stored    4 kept, 1 duplicate, 1 secure-field, 2 no-permission, 1 failed
  disk          299.3 KB in total, 0 B today (from kept records)
  warning: Screen Recording permission is missing since 2026-11-18 01:07 (1d 19h ago) (records say no-permission, and no screenshot was taken since). Grant it in System Settings > Privacy & Security > Screen Recording.
```

`screenshot` coverage is not checked: coverage is judged from `ax-text`
records, so the coverage gaps list says `screenshot: not checked` after the
`ax-text` check, and says nothing about screenshots when that check has
nothing to judge. With no screenshot records stored, the section is one line:

```
Screenshots: none stored yet (no screenshot records)
```

## backfill — one-time history import

```bash
computer-history backfill --dry-run           # show the plan, write nothing
computer-history backfill                     # run it
computer-history backfill --start 2026-11-01  # override where it starts
```

```
Backfilling http://127.0.0.1:5600/api/0 into .../history.db (7d chunks)
  aw-window (1 bucket): [2026-11-12 00:00, 2026-11-18 10:10) up to its settled-until time 2026-11-18 10:10, 1 chunk
  ...
  aw-window done in 2s: inserted 3,451, skipped 0, held back 1
  progress set: settled until 2026-11-18 10:05; `computer-history ingest` continues from there without re-reading history
```

Imports existing ActivityWatch history in 7-day chunks, oldest first, one
commit each. Safe to re-run; an interrupted run resumes by re-running. A
source with no ingest progress gets it in the last chunk's commit (only if the
range covers all its history); existing progress is never moved. A source
whose progress has no settled time is backfilled up to now and its progress
is left alone.

## rebuild-signals — regenerate the derived layer

```bash
computer-history rebuild-signals
computer-history rebuild-signals --allow-shrink   # a mapping change drops rows on purpose
```

```
Rebuilt signals in .../history.db from stored observations
  signals before        5,960
  signals after         5,960
  skipped                   0  (malformed payloads)
```

Wipes `signals` and re-projects every stored observation through its source
adapter's projector, the same one ingest used. Needed only after changing a
projector (`activitywatch/normalize.py`, `capture_spool/normalize.py`) or
`text.py`. Aborts (and rolls back) if too many rows fail to project or the
result would shrink suspiciously. It also aborts, without counting them as
malformed, when observations come from a source this version has no adapter
for:

```
rebuild-signals aborted: no source adapter projects 'screenshot', the source of 12 stored observations (first id: 7); rolled back, signals unchanged
  this computer-history has no adapter for that source; rebuild with the version that ingested it
```

## When the database can't be used

Every command opens the store the same way and refuses, with exit code 1 and
no traceback, when the database is:

- **newer** than this CLI (`cannot use ...: schema v6 is newer than this CLI
  understands (v5); upgrade computer-history`). Nothing is read or written.
- **busy** while opening for write, e.g. another process is migrating
  (`cannot open ...: database is locked` plus a try-again hint).
- **not a database** (`cannot open ...: file is not a database`).

An **outdated** schema is migrated by `ingest`, `backfill` and
`rebuild-signals`. `status` and `backfill --dry-run` never migrate: status
prints `note: this CLI uses schema v5; computer-history ingest will migrate
the database` and stops there, and a dry run refuses. A **missing** database
is created by `ingest` and `backfill` (only once planning succeeds), shown as
"not created yet" by `status`, and refused by `rebuild-signals`.

## Global flags

```bash
computer-history --db-path /tmp/scratch.db ingest   # or $COMPUTER_HISTORY_DB
computer-history status --aw-url http://127.0.0.1:5666/api/0
computer-history ingest --spool-path /tmp/spool     # or $COMPUTER_HISTORY_SPOOL
```

Every command takes `--db-path`; the networked ones (`ingest`, `status`,
`backfill`) take `--aw-url`. `ingest` and `status` also take `--spool-path`;
without it the spool is the `spool/` folder beside the database, so a scratch
database never collects the real spool. `-h` on any command prints its flags.
