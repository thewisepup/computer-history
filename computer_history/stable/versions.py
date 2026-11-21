from __future__ import annotations

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


def point(pointer: Path, name: str) -> None:
    """Link a pointer in the live folder to a version folder, replacing it in one step."""
    staged = pointer.with_name(f".{pointer.name}.new")
    staged.unlink(missing_ok=True)
    staged.symlink_to(Path(VERSIONS_FOLDER_NAME) / name)
    os.replace(staged, pointer)


def build_version(host: Host, layout: Layout, commit: str) -> bool:
    """Build a commit into its version folder unless it is already marked; returns whether it built.

    A failed build leaves no folder behind, not even the parents it created.
    """
    folder = layout.versions / version_name(commit)
    if (folder / INSTALL_MARKER_NAME).is_file():
        return False
    created = [path for path in (layout.live, layout.versions) if not path.exists()]
    if folder.exists():
        shutil.rmtree(folder)
    try:
        folder.mkdir(parents=True)
        packages = host.build(commit, folder / VENV_FOLDER_NAME)
        (folder / PACKAGES_FILE_NAME).write_text(packages, encoding="utf-8")
        (folder / INSTALL_MARKER_NAME).write_text("")
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        for path in reversed(created):
            path.rmdir()
        raise
    return True
