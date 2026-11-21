from __future__ import annotations

import os
from pathlib import Path

from computer_history.store import Profile, refuse_live_in_dev

SPOOL_ENV_VAR = "COMPUTER_HISTORY_SPOOL"
SPOOL_FOLDER_NAME = "spool"
AGENT_CONFIG_NAME = "agent-config.json"


def configured_spool_path(explicit: str | os.PathLike[str] | None, db_path: Path) -> Path:
    """Pick the spool folder: --spool-path, then $COMPUTER_HISTORY_SPOOL, then beside the database.

    Empty values count as unset, and ~ is expanded.
    """
    for candidate in (explicit, os.environ.get(SPOOL_ENV_VAR)):
        if candidate:
            return Path(candidate).expanduser()
    return db_path.parent / SPOOL_FOLDER_NAME


def resolve_spool_path(
    explicit: str | os.PathLike[str] | None, db_path: Path, profile: Profile
) -> Path:
    """The configured spool for a command that reads it; dev is refused the live folder."""
    path = configured_spool_path(explicit, db_path)
    default = db_path.parent / SPOOL_FOLDER_NAME
    refuse_live_in_dev(path, profile, flag="--spool-path", env_var=SPOOL_ENV_VAR, default=default)
    return path


def agent_config_path(db_path: Path) -> Path:
    """The config file the agent and the watchdog read sits beside the database."""
    return db_path.parent / AGENT_CONFIG_NAME
