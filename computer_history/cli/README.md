# computer-history CLI

The command line for the local activity store: it ingests settled
ActivityWatch events into SQLite and reports on what is stored. All business
logic lives in `sources/` and `store/`; this package only parses arguments,
calls one function, and formats the result.

```
app.py         parser + dispatch: one entry per command
  |
  +-- ingest.py    one poll, or the --watch loop
  +-- status.py    freshness, coverage gaps, row counts
  +-- rebuild.py   rebuild-signals
  +-- backfill.py  plan, then ingest history chunk by chunk
        |
shared.py (open the store) and formatting.py (durations, times, sizes)
```

Run it as `.venv/bin/computer-history`, or bare `computer-history` with the
venv activated (or aliased).

## ingest — the everyday command

```bash
computer-history ingest            # one poll: catch up since the cursor
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
Database:      .../ComputerHistory/history.db (5.2 MB, schema v2)
ActivityWatch: yes (http://127.0.0.1:5600/api/0; sources: aw-afk, aw-web, aw-window)

Sources:
  aw-window     3,451 observations  latest end 2026-11-18 10:10  cursor 2026-11-18 10:10 (5s behind now)
  ...
Coverage gaps (unobserved: nothing recorded) of 5m or more ...
  warning: no aw-web coverage from 2026-11-17 10:45 to 2026-11-17 12:25 (1h 39m)
```

Read-only: never creates, migrates or writes. Gaps are reported as
unobserved time, never assumed idle. Small cursor lag is normal — the cursor
waits at the start of the current, still-growing event.

## backfill — one-time history import

```bash
computer-history backfill --dry-run           # show the plan, write nothing
computer-history backfill                     # run it
computer-history backfill --start 2026-11-01  # override where it starts
```

```
Backfilling http://127.0.0.1:5600/api/0 into .../history.db (7d chunks)
  aw-window (1 bucket): [2026-11-12 00:00, 2026-11-18 10:10) up to its cursor, 1 chunk
```

Imports existing ActivityWatch history in 7-day chunks, oldest first, one
commit each. Safe to re-run; an interrupted run resumes by re-running.

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

## Global flags

```bash
computer-history --db-path /tmp/scratch.db ingest   # or $COMPUTER_HISTORY_DB
computer-history status --aw-url http://127.0.0.1:5666/api/0
```

Every command takes `--db-path`; the networked ones (`ingest`, `status`,
`backfill`) take `--aw-url`. `-h` on any command prints its flags.
