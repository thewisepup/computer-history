from __future__ import annotations

import math
from enum import Enum

PROGRESS_RECORDS = 5


class Outcome(Enum):
    OK = "ok"
    FAILED = "failed"  # a handled error stopped it
    ABORTED = "aborted"  # it refused to finish and rolled back
    INTERRUPTED = "interrupted"  # Ctrl-C or SIGINT
    CRASHED = "crashed"  # an unexpected exception ended it


def progress_step(total: int, *, at_least: int = 1) -> int:
    """How many units of work pass between progress records, so a run writes about five."""
    return max(at_least, math.ceil(total / PROGRESS_RECORDS))
