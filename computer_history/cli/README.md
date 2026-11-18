# computer-history CLI

The command line for the local activity store: it ingests settled
ActivityWatch events into SQLite and reports on what is stored. All business
logic lives in `sources/` and `store/`; this package only parses arguments,
builds the clients, source adapters and connection, calls one function, and
formats the result.

```
app.py         parser + dispatch: one entry per command
  |
  +-- ingest.py    one poll, or the --watch loop, through the ingest runner
  +-- status.py    freshness, coverage gaps, row counts
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
Ingested from http://127.0.0.1:5600/api/0 into .../ComputerHistory/history.db
  aw-afk     inserted      5  skipped      0  held back   1
  aw-web     inserted     62  skipped      1  held back   0
  aw-window  inserted    271  skipped      1  held back   1
```

`inserted` is new rows, `skipped` is events already stored (re-reads are
harmless), `held back` is events still growing — they land on a later poll.
Re-running always inserts 0 for data it already has. `--watch` is the
long-running collector: one log line per cycle, survives ActivityWatch
outages and locked databases.

## status — is everything healthy?

```bash
computer-history status
```

```
Database:      .../ComputerHistory/history.db (5.2 MB, schema v3)
ActivityWatch: yes (http://127.0.0.1:5600/api/0; sources: aw-afk, aw-web, aw-window)

Sources:
  aw-window     3,451 observations  latest end 2026-11-18 10:10  settled until 2026-11-18 10:10 (5s behind now)
  ...
Coverage gaps (unobserved: nothing recorded) of 5m or more ...
  warning: no aw-web coverage from 2026-11-17 10:45 to 2026-11-17 12:25 (1h 39m)
```

Read-only: never creates, migrates or writes. Gaps are reported as
unobserved time, never assumed idle, and are checked up to each source's
settled-until time. Small lag is normal — a source is settled only up to the
start of its current, still-growing event. A source whose progress has no
settled time shows `settled until - (progress moved 30s ago)` instead.

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

Wipes `signals` and re-projects every stored observation. Needed only after
changing `project_signal` or `text.py`. Aborts (and rolls back) if too many
rows fail to project or the result would shrink suspiciously.

## When the database can't be used

Every command opens the store the same way and refuses, with exit code 1 and
no traceback, when the database is:

- **newer** than this CLI (`cannot use ...: schema v4 is newer than this CLI
  understands (v3); upgrade computer-history`). Nothing is read or written.
- **busy** while opening for write, e.g. another process is migrating
  (`cannot open ...: database is locked` plus a try-again hint).
- **not a database** (`cannot open ...: file is not a database`).

An **outdated** schema is migrated by `ingest`, `backfill` and
`rebuild-signals`. `status` and `backfill --dry-run` never migrate: status
prints `note: this CLI uses schema v3; computer-history ingest will migrate
the database` and stops there, and a dry run refuses. A **missing** database
is created by `ingest` and `backfill` (only once planning succeeds), shown as
"not created yet" by `status`, and refused by `rebuild-signals`.

## Global flags

```bash
computer-history --db-path /tmp/scratch.db ingest   # or $COMPUTER_HISTORY_DB
computer-history status --aw-url http://127.0.0.1:5666/api/0
```

Every command takes `--db-path`; the networked ones (`ingest`, `status`,
`backfill`) take `--aw-url`. `-h` on any command prints its flags.
