"""The computer-history command line.

    app.py         parser + dispatch: one entry per command
      |
      +-- ingest.py    one poll, or the --watch loop, through the ingest runner
      |                (ActivityWatch and the capture spool in one loop)
      +-- status.py    freshness, coverage gaps, row counts
      +-- rebuild.py   rebuild-signals
      +-- backfill.py  plan, then ingest history chunk by chunk through the runner
            |
    db.py and sources.py (unusable database / source messages),
    formatting.py (durations, times, sizes)
"""

from computer_history.cli.app import COMMANDS, HANDLERS, build_parser, main

__all__ = [
    "COMMANDS",
    "HANDLERS",
    "build_parser",
    "main",
]
