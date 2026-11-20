from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path

DB_ENV_VAR = "COMPUTER_HISTORY_DB"


class LiveDatabaseRefused(ValueError):
    """The output would write into the live database's folder or the live spool."""


def default_db_path() -> Path:
    """The default database location in Application Support."""
    return Path.home() / "Library" / "Application Support" / "ComputerHistory" / "history.db"


def resolve_db_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Pick the database path: the --db-path value, then $COMPUTER_HISTORY_DB, then the default.

    Empty values count as unset, and ~ is expanded.
    """
    for candidate in (explicit, os.environ.get(DB_ENV_VAR)):
        if candidate:
            return Path(candidate).expanduser()
    return default_db_path()


def refuse_live(paths: Iterable[Path], live: Sequence[Path], *, replaced: bool = False) -> None:
    """Raise LiveDatabaseRefused for a path inside a live folder, or holding one when replaced."""
    for path in paths:
        for folder in live:
            if within(path, folder):
                raise LiveDatabaseRefused(
                    f"{path} is in {folder}, which holds the live database or spool"
                )
            if replaced and within(folder, path):
                raise LiveDatabaseRefused(
                    f"{path} holds {folder}, the live database's or spool's folder"
                )


def within(path: Path, folder: Path) -> bool:
    """Whether the path is the folder or inside it, ignoring case and following symlinks."""
    inner, outer = path.as_posix().casefold(), folder.as_posix().casefold()
    if inner == outer or inner.startswith(outer.rstrip("/") + "/"):
        return True
    return folder.exists() and any(
        candidate.exists() and os.path.samefile(candidate, folder)
        for candidate in (path, *path.parents)
    )
