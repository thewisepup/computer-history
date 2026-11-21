from __future__ import annotations

import contextlib
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from computer_history.host import Host
from computer_history.stable.layout import PACKAGES_FILE_NAME, VENV_FOLDER_NAME, Layout
from computer_history.store import INSTALL_MARKER_NAME, SHORT_COMMIT_LENGTH, VERSIONS_FOLDER_NAME


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


def replace_symlink(link: Path, target: Path) -> None:
    """Point a symlink at a target in one step, leaving nothing behind when that fails."""
    staged = link.with_name(f".{link.name}.new")
    staged.unlink(missing_ok=True)
    staged.symlink_to(target)
    try:
        os.replace(staged, link)
    except OSError:
        staged.unlink(missing_ok=True)
        raise


def make_current(host: Host, layout: Layout, commit: str) -> None:
    """Build a commit into its version folder unless it is marked already, then point current at it.

    On any failure everything this created is removed again before the error goes on.
    """
    name = version_name(commit)
    folder = layout.versions / name
    marked = (folder / INSTALL_MARKER_NAME).is_file()
    created = [path for path in (layout.live, layout.versions) if not path.exists()]
    try:
        if not marked:
            if folder.exists():
                shutil.rmtree(folder)
            folder.mkdir(parents=True)
            packages = host.build(commit, folder / VENV_FOLDER_NAME)
            (folder / PACKAGES_FILE_NAME).write_text(packages, encoding="utf-8")
            (folder / INSTALL_MARKER_NAME).write_text("")
        replace_symlink(layout.current, Path(VERSIONS_FOLDER_NAME) / name)
    except BaseException:
        if not marked:
            shutil.rmtree(folder, ignore_errors=True)
        if layout.versions in created:
            shutil.rmtree(layout.versions, ignore_errors=True)
        if layout.live in created:
            with contextlib.suppress(OSError):
                layout.live.rmdir()
        raise
