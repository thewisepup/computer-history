"""A dev database: a cached dataset copied out for local use, never over the live database."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from computer_history.sources import resolve_spool_path
from computer_history.store import default_db_path, resolve_db_path
from computer_history.synthetic.build import DATABASE_NAME, MANIFEST_NAME, SIDECARS
from computer_history.synthetic.cache import CachedDataset, cached_dataset, copy_dataset
from computer_history.synthetic.generate import DatasetInputs

KNOWN_NAMES = (MANIFEST_NAME, DATABASE_NAME, *(DATABASE_NAME + suffix for suffix in SIDECARS))


class LiveDatabaseRefused(ValueError):
    """The output would write into the live database's folder or the live spool."""


class OutputNotAFolder(NotADirectoryError):
    """The output path is a file, not a folder."""


class OutputExists(FileExistsError):
    """The output folder already holds files the dataset would replace."""


@dataclass(frozen=True)
class DevDatabase:
    """Where a dataset was copied, and the cache entry it came from."""

    dataset: CachedDataset
    copied: tuple[Path, ...]


def live_folders(explicit_db: str | os.PathLike[str] | None = None) -> tuple[Path, ...]:
    """The folders of the default, configured and given databases, and the configured spool."""
    databases = {default_db_path(), resolve_db_path(), resolve_db_path(explicit_db)}
    folders = {db.parent for db in databases} | {resolve_spool_path(None, default_db_path())}
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
    _refuse_live([target], live)
    if target.exists() and not target.is_dir():
        raise OutputNotAFolder(f"{out} is a file, not a folder")
    _refuse_existing(out, _in_the_way(target, KNOWN_NAMES), force)
    dataset = cached_dataset(inputs, cache)
    names = [*(item.name for item in sorted(dataset.folder.iterdir())), *KNOWN_NAMES]
    _refuse_live([target / name for name in names], live, replaced=True)
    in_the_way = _in_the_way(target, names)
    _refuse_existing(out, in_the_way, force)
    for path in in_the_way:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    return DevDatabase(dataset, copy_dataset(dataset, target))


def _refuse_live(paths: Iterable[Path], live: Sequence[Path], *, replaced: bool = False) -> None:
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


def _refuse_existing(out: Path, in_the_way: Sequence[Path], force: bool) -> None:
    if in_the_way and not force:
        names = ", ".join(path.name for path in in_the_way)
        raise OutputExists(f"{out} already holds {names}; pass --force to replace them")


def _in_the_way(target: Path, names: Iterable[str]) -> list[Path]:
    found = {target / name for name in names}
    return sorted(path for path in found if path.exists() or path.is_symlink())
