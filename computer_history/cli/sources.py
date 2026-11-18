"""Messages for a source a command cannot read."""

from __future__ import annotations

import sys

SOURCE_HINT = "Is ActivityWatch running? Check with `computer-history status`."


def source_failed(error: str, *, stream: str | None = None) -> int:
    """Print the source's error and the hint, and return the exit code."""
    where = f" on {stream}" if stream else ""
    print(f"error{where}: {error}", file=sys.stderr)
    print(SOURCE_HINT, file=sys.stderr)
    return 1
