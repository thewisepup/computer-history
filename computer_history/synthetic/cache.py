"""Built datasets cached per user and shared by every worktree, keyed by what shapes them."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from computer_history.store import connect_immutable, supported_version
from computer_history.synthetic.build import DATABASE_NAME, MANIFEST_NAME, build_dataset
from computer_history.synthetic.generate import DatasetInputs

CACHE_ENV_VAR = "COMPUTER_HISTORY_DATASET_CACHE"
PACKAGE = Path(__file__).resolve().parents[1]
CODE_SUFFIXES = (".py", ".sql")

Build = Callable[[DatasetInputs, Path], object]


@dataclass(frozen=True)
class CachedDataset:
    """A complete cache entry, and whether this request built it."""

    key: str
    folder: Path
    built: bool

    @property
    def db_path(self) -> Path:
        return self.folder / DATABASE_NAME

    @property
    def manifest_path(self) -> Path:
        return self.folder / MANIFEST_NAME


def cache_root() -> Path:
    """The cache folder: $COMPUTER_HISTORY_DATASET_CACHE, else the user cache folder."""
    configured = os.environ.get(CACHE_ENV_VAR)
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ComputerHistory" / "datasets"
    xdg = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(xdg) / "computer-history" / "datasets"


def dataset_key(inputs: DatasetInputs, code: Path = PACKAGE) -> str:
    """A hash of the inputs, package code and migrations, and schema, SQLite and Python versions."""
    digest = hashlib.sha256()
    versions = {
        "inputs": dataclasses.asdict(inputs),
        "schema": supported_version(),
        "sqlite": sqlite3.sqlite_version,
        "python": list(sys.version_info[:2]),
    }
    digest.update(json.dumps(versions, sort_keys=True, default=str).encode())
    for path in sorted(code.rglob("*")):
        if path.suffix not in CODE_SUFFIXES or "__pycache__" in path.parts:
            continue
        name = path.relative_to(code).as_posix().encode()
        body = path.read_bytes()
        digest.update(b"%d:%s%d:" % (len(name), name, len(body)) + body)
    return digest.hexdigest()[:32]


def cached_dataset(
    inputs: DatasetInputs, root: Path, build: Build = build_dataset
) -> CachedDataset:
    """The entry for the inputs, built in a temporary folder and renamed into place if missing.

    A build that loses the race to another discards its copy and returns the winner's entry.
    """
    key = dataset_key(inputs)
    entry = root / key
    if _complete(entry):
        return CachedDataset(key, entry, built=False)
    root.mkdir(parents=True, exist_ok=True)
    if entry.exists():
        _discard(entry, root / f".{key}.{uuid.uuid4().hex}.damaged")
    staging = root / f".{key}.{uuid.uuid4().hex}.partial"
    try:
        build(inputs, staging)
        staging.rename(entry)
    except OSError:
        if not _complete(entry):
            raise
        return CachedDataset(key, entry, built=False)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return CachedDataset(key, entry, built=True)


def _complete(entry: Path) -> bool:
    return (entry / DATABASE_NAME).is_file() and (entry / MANIFEST_NAME).is_file()


def _discard(entry: Path, aside: Path) -> None:
    try:
        entry.rename(aside)
    except FileNotFoundError:
        return
    shutil.rmtree(aside, ignore_errors=True)


def open_cached(dataset: CachedDataset) -> sqlite3.Connection:
    """Open the entry's database for reading only."""
    return connect_immutable(dataset.db_path)


def copy_dataset(dataset: CachedDataset, destination: Path) -> tuple[Path, ...]:
    """Copy every file of the entry into the destination folder; returns the top-level paths."""
    destination.mkdir(parents=True, exist_ok=True)
    copied = []
    for item in sorted(dataset.folder.iterdir()):
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, copy_function=shutil.copyfile)
        else:
            shutil.copyfile(item, target)
        copied.append(target)
    return tuple(copied)
