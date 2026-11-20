"""A dev database: a cached dataset copied out for local use, never over the live database."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from computer_history.store import DB_ENV_VAR, default_db_path
from computer_history.synthetic.cache import CachedDataset, cached_dataset, copy_dataset
from computer_history.synthetic.generate import DatasetInputs

SIDECARS = ("-wal", "-shm", "-journal")


class LiveDatabaseRefused(ValueError):
    """The output is the live database or lies in its folder."""


class OutputExists(FileExistsError):
    """The output folder already holds files the dataset would replace."""


@dataclass(frozen=True)
class DevDatabase:
    """Where a dataset was copied, and the cache entry it came from."""

    dataset: CachedDataset
    copied: tuple[Path, ...]


def live_databases() -> tuple[Path, ...]:
    """The default database location, and $COMPUTER_HISTORY_DB when it is set."""
    configured = os.environ.get(DB_ENV_VAR)
    found = [default_db_path(), *([Path(configured).expanduser()] if configured else [])]
    return tuple(path.resolve() for path in found)


def make_dev_database(inputs: DatasetInputs, out: Path, *, force: bool = False) -> DevDatabase:
    """Build or reuse the cached dataset and copy its files into the out folder.

    Refuses the live database and its folder, and files already in the way unless forced.
    """
    target = out.expanduser().resolve()
    for live in live_databases():
        if target == live or target.is_relative_to(live.parent):
            raise LiveDatabaseRefused(f"{out} is the live database {live} or inside its folder")
    if target.exists() and not target.is_dir():
        raise NotADirectoryError(f"{out} is a file, not a folder")
    dataset = cached_dataset(inputs)
    in_the_way = _in_the_way(dataset, target)
    if in_the_way and not force:
        names = ", ".join(path.name for path in in_the_way)
        raise OutputExists(f"{out} already holds {names}; pass --force to replace them")
    for path in in_the_way:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    return DevDatabase(dataset, copy_dataset(dataset, target))


def _in_the_way(dataset: CachedDataset, target: Path) -> list[Path]:
    names = [item.name for item in sorted(dataset.folder.iterdir())]
    names += [dataset.db_path.name + suffix for suffix in SIDECARS]
    return [
        target / name for name in names if (target / name).exists() or (target / name).is_symlink()
    ]
