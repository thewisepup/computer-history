"""The computer-history command line.

::

    app.py         parser + dispatch: one entry per command
      |
      +-- ingest.py    one poll, or the --watch loop
      +-- status.py    freshness, coverage gaps, row counts
      +-- rebuild.py   rebuild-signals
      +-- backfill.py  plan, then ingest history chunk by chunk
            |
    shared.py (open the store) and formatting.py (durations, times, sizes)
"""

from computer_history.cli.app import COMMANDS, HANDLERS, build_parser, main
from computer_history.cli.ingest import (
    POLL_INTERVAL_SECONDS,
    CycleSummary,
    run_cycle,
    watch,
)

__all__ = [
    "COMMANDS",
    "HANDLERS",
    "POLL_INTERVAL_SECONDS",
    "CycleSummary",
    "build_parser",
    "main",
    "run_cycle",
    "watch",
]
