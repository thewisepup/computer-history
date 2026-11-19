"""Messages for a source a command cannot read."""

from __future__ import annotations

import sys

from computer_history.sources import AX_TEXT_SOURCE

SOURCE_HINT = "Is ActivityWatch running? Check with `computer-history status`."
SPOOL_HINT = "Can this user list, read and change files in the spool folder?"


def source_failed(error: str, *, stream: str | None = None) -> int:
    """Print the source's error and the hint for that source, and return the exit code."""
    where = f" on {stream}" if stream else ""
    print(f"error{where}: {error}", file=sys.stderr)
    print(SPOOL_HINT if stream == AX_TEXT_SOURCE else SOURCE_HINT, file=sys.stderr)
    return 1
