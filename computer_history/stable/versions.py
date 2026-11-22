from __future__ import annotations

import contextlib
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from computer_history.host import Host
from computer_history.stable.layout import PACKAGES_FILE_NAME, VENV_FOLDER_NAME, Layout
from computer_history.store import (
    INSTALL_MARKER_NAME,
    SHORT_COMMIT_LENGTH,
    VERSIONS_FOLDER_NAME,
    load_migrations,
    replace_atomically,
)

PACKAGE_MIGRATIONS = "lib/python*/site-packages/computer_history/store/migrations"


@dataclass(frozen=True)
class InstalledVersion:
    """A marked version folder: its name (the short commit) and when its build finished."""

    name: str
    installed_at: datetime


def version_name(commit: str) -> str:
    return commit[:SHORT_COMMIT_LENGTH]


def pointed(pointer: Path) -> InstalledVersion | None:
    """The marked version a pointer links to, or None when it is missing or links elsewhere."""
    if not pointer.is_symlink():
        return None
    marker = pointer.resolve() / INSTALL_MARKER_NAME
    if not marker.is_file():
        return None
    return InstalledVersion(marker.parent.name, datetime.fromtimestamp(marker.stat().st_mtime, UTC))


def supported_schema(layout: Layout, name: str) -> int | None:
    """The newest schema version a version folder's code migrates to, or None if it can't tell."""
    found = sorted((layout.versions / name / VENV_FOLDER_NAME).glob(PACKAGE_MIGRATIONS))
    if not found:
        return None
    try:
        migrations = load_migrations(found[-1])
    except (OSError, RuntimeError):
        return None
    return migrations[-1].version if migrations else None


def replace_symlink(link: Path, target: Path) -> None:
    """Point a symlink at a target in one step, leaving nothing behind when that fails."""
    replace_atomically(link, lambda staged: staged.symlink_to(target))


def point(pointer: Path, name: str) -> None:
    """Point current or previous at a version folder, by a path relative to the live folder."""
    replace_symlink(pointer, Path(VERSIONS_FOLDER_NAME) / name)


def build_version(host: Host, layout: Layout, commit: str) -> bool:
    """Build a commit into its marked version folder, noting what its backend reads, unless marked
    already; True if it built one."""
    folder = layout.versions / version_name(commit)
    if (folder / INSTALL_MARKER_NAME).is_file():
        return False
    try:
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        built = host.build(commit, folder / VENV_FOLDER_NAME)
        (folder / PACKAGES_FILE_NAME).write_text(built.packages, encoding="utf-8")
        layout.spool_reads(folder).write_text(f"{built.reads.as_json()}\n", encoding="utf-8")
        (folder / INSTALL_MARKER_NAME).write_text("")
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return True


def make_current(host: Host, layout: Layout, commit: str) -> None:
    """Build a commit into its version folder unless it is marked already, then point current at it.

    On any failure everything this created is removed again before the error goes on.
    """
    name = version_name(commit)
    created = [path for path in (layout.live, layout.versions) if not path.exists()]
    built = False
    try:
        built = build_version(host, layout, commit)
        point(layout.current, name)
    except BaseException:
        if built:
            shutil.rmtree(layout.versions / name, ignore_errors=True)
        if layout.versions in created:
            shutil.rmtree(layout.versions, ignore_errors=True)
        if layout.live in created:
            with contextlib.suppress(OSError):
                layout.live.rmdir()
        raise
