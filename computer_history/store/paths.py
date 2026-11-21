from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

DB_ENV_VAR = "COMPUTER_HISTORY_DB"
DATABASE_NAME = "history.db"
LIVE_FOLDER_NAME = "ComputerHistory"
DEV_FOLDER_NAME = "ComputerHistory-dev"
VERSIONS_FOLDER_NAME = "versions"
INSTALL_MARKER_NAME = "installed"
SHORT_COMMIT_LENGTH = 7
SIDECARS = ("-wal", "-shm", "-journal")


class Profile(Enum):
    STABLE = "stable"
    DEV = "dev"


@dataclass(frozen=True)
class RunningCode:
    """The profile of the running code, and the stable version it runs from when stable."""

    profile: Profile
    version: str | None = None


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


def running_code(code: Path) -> RunningCode:
    """Stable when the code runs from a version folder of the stable install that has the marker.

    Anything else, a checkout, a worktree, a venv install or an unmarked version, is dev.
    """
    versions = live_folder() / VERSIONS_FOLDER_NAME
    resolved = code.expanduser().resolve()
    inside = [
        folder
        for folder in (resolved, *resolved.parents)
        if _within(folder, versions) and not _within(versions, folder)
    ]
    if not inside or not (inside[-1] / INSTALL_MARKER_NAME).is_file():
        return RunningCode(Profile.DEV)
    return RunningCode(Profile.STABLE, inside[-1].name)


def sidecars(db_path: Path) -> tuple[Path, ...]:
    """The journal files SQLite keeps beside a database."""
    return tuple(db_path.with_name(db_path.name + suffix) for suffix in SIDECARS)


def existing_database_files(db_path: Path) -> list[Path]:
    """The database file and its journal files that already exist, dangling links included."""
    return [path for path in (db_path, *sidecars(db_path)) if path.exists() or path.is_symlink()]


def default_db_path(profile: Profile) -> Path:
    """The profile's default database location."""
    return data_folder(profile) / DATABASE_NAME


def configured_db_path(explicit: str | os.PathLike[str] | None, profile: Profile) -> Path:
    """Pick the database path: the --db-path value, then $COMPUTER_HISTORY_DB, then the default.

    Empty values count as unset, and ~ is expanded.
    """
    for candidate in (explicit, os.environ.get(DB_ENV_VAR)):
        if candidate:
            return Path(candidate).expanduser()
    return default_db_path(profile)


def resolve_db_path(explicit: str | os.PathLike[str] | None, profile: Profile) -> Path:
    """The configured database path for a command that opens it; dev is refused the live folder."""
    path = configured_db_path(explicit, profile)
    default = default_db_path(profile)
    refuse_live_in_dev(path, profile, flag="--db-path", env_var=DB_ENV_VAR, default=default)
    return path


def resolve_dev_db_path(explicit: str | os.PathLike[str] | None) -> Path:
    """Dev's configured database path under either profile, refused inside the live folder."""
    path = configured_db_path(explicit, Profile.DEV)
    if _in_live_folder(path):
        raise LiveDatabaseRefused(
            f"{path} is in the live data folder {live_folder()}, and the dev database is never"
            " there, whichever profile runs. Leave --db-path and"
            f" ${DB_ENV_VAR} unset to use {default_db_path(Profile.DEV)}."
        )
    return path


def refuse_live_in_dev(
    path: Path, profile: Profile, *, flag: str, env_var: str, default: Path
) -> None:
    """Raise LiveDatabaseRefused when a dev run's path is in the live folder or links into it."""
    if profile is Profile.STABLE or not _in_live_folder(path):
        return
    raise LiveDatabaseRefused(
        f"{path} is in the live data folder {live_folder()}. This run is dev (its code is a"
        " checkout or worktree, not the stable install), and dev never uses live data. Leave"
        f" {flag} and ${env_var} unset to use {default}, or run the stable install's"
        " computer-history."
    )


def _in_live_folder(path: Path) -> bool:
    return _within(path.resolve(), live_folder().resolve())


def refuse_live(paths: Iterable[Path], live: Sequence[Path], *, replaced: bool = False) -> None:
    """Raise LiveDatabaseRefused for a path inside a live folder, or holding one when replaced."""
    for path in paths:
        for folder in live:
            if _within(path, folder):
                raise LiveDatabaseRefused(
                    f"{path} is in {folder}, which holds the live database or spool"
                )
            if replaced and _within(folder, path):
                raise LiveDatabaseRefused(
                    f"{path} holds {folder}, the live database's or spool's folder"
                )


def _within(path: Path, folder: Path) -> bool:
    inner, outer = path.as_posix().casefold(), folder.as_posix().casefold()
    if inner == outer or inner.startswith(outer.rstrip("/") + "/"):
        return True
    return folder.exists() and any(
        candidate.exists() and os.path.samefile(candidate, folder)
        for candidate in (path, *path.parents)
    )
