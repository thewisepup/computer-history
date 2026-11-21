from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from enum import Enum
from pathlib import Path

DB_ENV_VAR = "COMPUTER_HISTORY_DB"
DATABASE_FILE_NAME = "history.db"
LIVE_FOLDER_NAME = "ComputerHistory"
DEV_FOLDER_NAME = "ComputerHistory-dev"
VERSIONS_FOLDER_NAME = "versions"
INSTALL_MARKER_NAME = "installed"


class Profile(Enum):
    STABLE = "stable"
    DEV = "dev"


class LiveDatabaseRefused(ValueError):
    """A path would use the live database's folder, the live spool or other live data."""


def live_folder() -> Path:
    """The stable install's data folder in Application Support, which holds the live data."""
    return Path.home() / "Library" / "Application Support" / LIVE_FOLDER_NAME


def data_folder(profile: Profile) -> Path:
    """The folder a profile keeps its database, spool and screenshots in by default."""
    if profile is Profile.STABLE:
        return live_folder()
    return live_folder().with_name(DEV_FOLDER_NAME)


def stable_version(code: Path) -> str | None:
    """The installed version the code runs from, or None when it is not the stable install.

    That is the version folder in the live versions folder holding the code, once it has the marker.
    """
    versions = live_folder() / VERSIONS_FOLDER_NAME
    resolved = code.expanduser().resolve()
    inside = [
        folder
        for folder in (resolved, *resolved.parents)
        if within(folder, versions) and not within(versions, folder)
    ]
    if not inside or not (inside[-1] / INSTALL_MARKER_NAME).is_file():
        return None
    return inside[-1].name


def profile_of(code: Path) -> Profile:
    """Stable when the code runs from a marked version of the stable install, else dev."""
    return Profile.DEV if stable_version(code) is None else Profile.STABLE


def default_db_path(profile: Profile) -> Path:
    """The profile's default database location."""
    return data_folder(profile) / DATABASE_FILE_NAME


def resolve_db_path(explicit: str | os.PathLike[str] | None, profile: Profile) -> Path:
    """Pick the database path: the --db-path value, then $COMPUTER_HISTORY_DB, then the default.

    Empty values count as unset, ~ is expanded, and dev is refused a path in the live folder.
    """
    default = default_db_path(profile)
    path = default
    for candidate in (explicit, os.environ.get(DB_ENV_VAR)):
        if candidate:
            path = Path(candidate).expanduser()
            break
    refuse_live_in_dev(path, profile, flag="--db-path", env_var=DB_ENV_VAR, default=default)
    return path


def refuse_live_in_dev(
    path: Path, profile: Profile, *, flag: str, env_var: str, default: Path
) -> None:
    """Raise LiveDatabaseRefused when a dev run's path is in the live folder or links into it."""
    live = live_folder()
    if profile is Profile.STABLE or not within(path.resolve(), live.resolve()):
        return
    raise LiveDatabaseRefused(
        f"{path} is in the live data folder {live}. This run is dev (its code is a checkout or"
        " worktree, not the stable install), and dev never uses live data. Leave"
        f" {flag} and ${env_var} unset to use {default}, or run the stable install's"
        " computer-history."
    )


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
