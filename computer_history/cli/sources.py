from __future__ import annotations

import sys

from computer_history.sources import SPOOL_STREAMS

AW_CHECK_TIMEOUT_SECONDS = 5
SOURCE_HINT = "Is ActivityWatch running? Check with `computer-history status`."
SPOOL_HINT = "Can this user list, read and change files in the spool folder?"


def unavailable_on(stream: str | None) -> str:
    """Where an unavailable source failed: the spool for either spool stream, else the stream."""
    if stream in SPOOL_STREAMS:
        return " on the spool"
    return f" on {stream}" if stream else ""


def source_failed(error: str, *, stream: str | None = None) -> int:
    """Print the source's error and the hint for that source, and return the exit code."""
    print(f"error{unavailable_on(stream)}: {error}", file=sys.stderr)
    print(SPOOL_HINT if stream in SPOOL_STREAMS else SOURCE_HINT, file=sys.stderr)
    return 1
