"""The computer-history command line.

app.py         parser + dispatch: one entry per command
  |
  +-- ingest.py    one poll, or the --watch loop, through the ingest runner
  |                (ActivityWatch and the capture spool in one loop)
  +-- status.py    freshness, coverage gaps, row counts
  +-- rebuild.py   rebuild-signals
  +-- backfill.py  plan, then ingest history chunk by chunk through the runner
  +-- logs.py      the JSON log's records, filtered, as text or raw lines
  +-- dev.py       dev build-db (a database of synthetic history from the dataset cache),
        |          dev perf (the performance gate), dev bench (wall-clock timings)
        |
db.py and sources.py (unusable database / source messages),
formatting.py (durations, times, sizes, app names)
"""

from computer_history.cli.app import COMMANDS, HANDLERS, build_parser, main

__all__ = [
    "COMMANDS",
    "HANDLERS",
    "build_parser",
    "main",
]
