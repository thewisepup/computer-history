"""A dev database: a cached dataset copied out for local use, never over the live database."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from computer_history.sources import configured_spool_path
from computer_history.store import (
    Profile,
    configured_db_path,
    default_db_path,
    existing_database_files,
    live_folder,
    refuse_live,
    sidecars,
)
from computer_history.synthetic.build import DATABASE_NAME, MANIFEST_NAME
from computer_history.synthetic.cache import CachedDataset, cached_dataset, copy_dataset
from computer_history.synthetic.generate import DatasetInputs

KNOWN_DATABASE_NAMES = (DATABASE_NAME, *(path.name for path in sidecars(Path(DATABASE_NAME))))
KNOWN_NAMES = (MANIFEST_NAME, *KNOWN_DATABASE_NAMES)


class OutputNotAFolder(NotADirectoryError):
    """The output path is a file, not a folder."""


class OutputExists(FileExistsError):
    """The output folder already holds files the dataset would replace."""


@dataclass(frozen=True)
class DevDatabase:
    """Where a dataset was copied, and the cache entry it came from."""

    dataset: CachedDataset
    copied: tuple[Path, ...]


def live_folders(
    explicit_db: str | os.PathLike[str] | None, profile: Profile
) -> tuple[Path, ...]:
    """The live folder, the default, configured and given databases' folders, and the spool."""
    default = default_db_path(profile)
    configured = (configured_db_path(None, profile), configured_db_path(explicit_db, profile))
    folders = {live_folder(), default.parent, *(db.parent for db in configured)}
    folders.add(configured_spool_path(None, default))
    return tuple(sorted(folder.expanduser().resolve() for folder in folders))


def make_dev_database(
    inputs: DatasetInputs,
    out: Path,
    *,
    cache: Path,
    live: Sequence[Path],
    force: bool = False,
) -> DevDatabase:
    """Build or reuse the cached dataset and copy its files into the out folder.

    Refuses to write into a live folder, and replaces files already there only when forced.
    """
    target = out.expanduser().resolve()
    refuse_live([target], live)
    if target.exists() and not target.is_dir():
        raise OutputNotAFolder(f"{out} is a file, not a folder")
    _refuse_existing(out, _in_the_way(target, KNOWN_NAMES), force)
    dataset = cached_dataset(inputs, cache)
    names = [*(item.name for item in sorted(dataset.folder.iterdir())), *KNOWN_NAMES]
    refuse_live([target / name for name in names], live, replaced=True)
    in_the_way = _in_the_way(target, names)
    _refuse_existing(out, in_the_way, force)
    for path in in_the_way:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    return DevDatabase(dataset, copy_dataset(dataset, target))


def _refuse_existing(out: Path, in_the_way: Sequence[Path], force: bool) -> None:
    if in_the_way and not force:
        names = ", ".join(path.name for path in in_the_way)
        raise OutputExists(f"{out} already holds {names}; pass --force to replace them")


def _in_the_way(target: Path, names: Iterable[str]) -> list[Path]:
    found = {target / name for name in names if name not in KNOWN_DATABASE_NAMES}
    others = {path for path in found if path.exists() or path.is_symlink()}
    return sorted(others.union(existing_database_files(target / DATABASE_NAME)))
