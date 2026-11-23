"""The computer-history command line.

app.py         parser + dispatch: one entry per command, the log folder of the
  |              profile, and the install lock around the commands that change
  |              the stable install
  +-- ingest.py    one poll, or the --watch loop, through the ingest runner
  |                (ActivityWatch and the capture spool in one loop), with
  |                the ingest health file, the cycle's log record and the
  |                failure streak's notification after each cycle, and spool deletion
  |                held until a cycle completes while update asks for it
  +-- status.py    the status report formatted: the given database's ingest,
  |                freshness, coverage gaps, row counts and backups, then the
  |                stable install's version and last update, its LaunchAgents and
  |                the watchdog's findings
  +-- rebuild.py   rebuild-signals
  +-- backfill.py  plan, then ingest history chunk by chunk through the runner
  +-- install.py   install and uninstall the stable install, through the host adapter
  +-- agent_guard.py  check-agent-install: whether this checkout's capture agent
  |                may be installed by hand, the unmet conditions and their fixes
  +-- update.py    update (to the newest passing commit, falling back on its own)
  |                and rollback (to the previous version, if it opens the database)
  +-- backup.py    backup (the day's backup, the oldest past seven removed) and
  |                restore (a backup put in place, the backend, watchdog and daily
  |                backup stopped around it)
  +-- logs.py      the JSON log's records, filtered, as text or raw lines
  +-- watchdog.py  one watchdog run: check, notify, reopen ActivityWatch, and its
  |                findings as lines
  +-- dev.py       dev build-db (a database of synthetic history from the dataset cache),
        |          dev snapshot (the live database copied into the dev folder),
        |          dev perf (the performance gate), dev bench (wall-clock timings)
        |
profile.py (the first line: profile, version or checkout, database),
db.py and sources.py (unusable database / source messages, and the ActivityWatch
timeout status and the watchdog share),
formatting.py (durations, times, sizes, app names, watchdog findings as lines, and
the clock every command reads)
"""

from computer_history.cli.app import COMMANDS, build_parser, main

__all__ = [
    "COMMANDS",
    "build_parser",
    "main",
]
