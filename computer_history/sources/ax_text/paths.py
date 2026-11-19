"""Where the spool folder is."""

from __future__ import annotations

import os
from pathlib import Path

SPOOL_ENV_VAR = "COMPUTER_HISTORY_SPOOL"
SPOOL_FOLDER_NAME = "spool"


def resolve_spool_path(explicit: str | os.PathLike[str] | None, db_path: Path) -> Path:
    """Pick the spool folder: --spool-path, then $COMPUTER_HISTORY_SPOOL, then beside the database.

    Empty values count as unset, and ~ is expanded.
    """
    for candidate in (explicit, os.environ.get(SPOOL_ENV_VAR)):
        if candidate:
            return Path(candidate).expanduser()
    return db_path.parent / SPOOL_FOLDER_NAME
