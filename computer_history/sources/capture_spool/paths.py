from __future__ import annotations

import os
from pathlib import Path

from computer_history.store import Profile, refuse_live_in_dev

SPOOL_ENV_VAR = "COMPUTER_HISTORY_SPOOL"
SPOOL_FOLDER_NAME = "spool"


def resolve_spool_path(
    explicit: str | os.PathLike[str] | None, db_path: Path, profile: Profile
) -> Path:
    """Pick the spool folder: --spool-path, then $COMPUTER_HISTORY_SPOOL, then beside the database.

    Empty values count as unset, ~ is expanded, and dev is refused a folder in the live folder.
    """
    default = db_path.parent / SPOOL_FOLDER_NAME
    path = default
    for candidate in (explicit, os.environ.get(SPOOL_ENV_VAR)):
        if candidate:
            path = Path(candidate).expanduser()
            break
    refuse_live_in_dev(path, profile, flag="--spool-path", env_var=SPOOL_ENV_VAR, default=default)
    return path
