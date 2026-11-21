"""The computer-history command line.

    app.py         parser + dispatch: one entry per command
      |
      +-- ingest.py    one poll, or the --watch loop, through the ingest runner
      |                (ActivityWatch and the capture spool in one loop), with
      |                the backend heartbeat after each cycle
      +-- status.py    freshness, coverage gaps, row counts, the install, its
      |                LaunchAgents, the backend's last cycle, the backups and the
      |                watchdog's findings
      +-- rebuild.py   rebuild-signals
      +-- backfill.py  plan, then ingest history chunk by chunk through the runner
      +-- install.py   install and uninstall the stable install, through the host adapter
      +-- backup.py    backup (the day's backup, the oldest past seven removed) and
      |                restore (a backup put in place, the backend stopped around it)
      +-- watchdog.py  one watchdog run: check, notify, reopen ActivityWatch, and its
      |                findings as lines, which status shows too
      +-- dev.py       dev build-db (a database of synthetic history from the dataset cache),
            |          dev snapshot (the live database copied into the dev folder),
            |          dev perf (the performance gate), dev bench (wall-clock timings)
            |
    profile.py (the first line: profile, version or checkout, database),
    db.py and sources.py (unusable database / source messages, and the ActivityWatch
    timeout status and the watchdog share),
    formatting.py (durations, times, sizes, app names, and the clock every command reads)
"""

from computer_history.cli.app import COMMANDS, HANDLERS, build_parser, main

__all__ = [
    "COMMANDS",
    "HANDLERS",
    "build_parser",
    "main",
]
