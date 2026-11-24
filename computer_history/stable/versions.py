from __future__ import annotations

import contextlib
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum, auto
from pathlib import Path
from typing import assert_never

from computer_history.host import Host
from computer_history.stable.layout import PACKAGES_FILE_NAME, VENV_FOLDER_NAME, Layout
from computer_history.store import (
    INSTALL_MARKER_NAME,
    SHORT_COMMIT_LENGTH,
    VERSIONS_FOLDER_NAME,
    load_migrations,
    replace_atomically,
)
from computer_history.transitions import TransitionTable

PACKAGE_MIGRATIONS = "lib/python*/site-packages/computer_history/store/migrations"
SHORT_COMMIT_HASH = re.compile(f"[0-9a-f]{{{SHORT_COMMIT_LENGTH}}}")


class VersionState(Enum):
    ABSENT = auto()
    PARTIAL = auto()
    MARKED_NO_AGENT = auto()
    COMPLETE = auto()


VERSION_FOLDERS = TransitionTable(
    "version folder",
    {
        VersionState.ABSENT: frozenset({VersionState.MARKED_NO_AGENT}),
        VersionState.PARTIAL: frozenset({VersionState.ABSENT, VersionState.MARKED_NO_AGENT}),
        VersionState.MARKED_NO_AGENT: frozenset(
            {VersionState.ABSENT, VersionState.MARKED_NO_AGENT, VersionState.COMPLETE}
        ),
        VersionState.COMPLETE: frozenset(
            {VersionState.ABSENT, VersionState.MARKED_NO_AGENT, VersionState.COMPLETE}
        ),
    },
)


class UnsafeVersionFolder(ValueError):
    """A version name that is not a short commit hash, or whose folder lies outside versions."""


@dataclass(frozen=True)
class InstalledVersion:
    """A marked version folder: its name (the short commit) and when its build finished."""

    name: str
    installed_at: datetime


def version_name(commit: str) -> str:
    return commit[:SHORT_COMMIT_LENGTH]


def version_folder(layout: Layout, name: str) -> Path:
    """The folder a version of this name is built in, refused unless it sits right in versions."""
    if not SHORT_COMMIT_HASH.fullmatch(name):
        raise UnsafeVersionFolder(f"refused version {name!r:.60}: not a short commit hash")
    folder = layout.versions / name
    if folder.resolve().parent != layout.versions.resolve():
        raise UnsafeVersionFolder(f"refused version {name}: not directly in {layout.versions}")
    return folder


def version_state(layout: Layout, folder: Path) -> VersionState:
    """How far a version folder on disk has got: absent, partly built, marked without an agent
    app and the note of its commit, or complete."""
    if not folder.exists():
        return VersionState.ABSENT
    if not _marker(folder).is_file():
        return VersionState.PARTIAL
    if carried_agent(layout, folder) is None:
        return VersionState.MARKED_NO_AGENT
    return VersionState.COMPLETE


def stepped(layout: Layout, folder: Path, before: VersionState) -> VersionState:
    """The state a step left a version folder in, refused when its table does not allow it."""
    return VERSION_FOLDERS.move(before, version_state(layout, folder))


def carried_agent(layout: Layout, version: Path) -> str | None:
    """The commit a version folder's agent app was built from, or None without an app or note."""
    if not layout.agent_app(version).is_dir():
        return None
    try:
        return layout.agent_commit(version).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def pointed(pointer: Path) -> InstalledVersion | None:
    """The marked version a pointer links to, or None when it is missing or links elsewhere."""
    if not pointer.is_symlink():
        return None
    marker = _marker(pointer.resolve())
    if not marker.is_file():
        return None
    return InstalledVersion(marker.parent.name, datetime.fromtimestamp(marker.stat().st_mtime, UTC))


def _marker(folder: Path) -> Path:
    return folder / INSTALL_MARKER_NAME


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
    """Build a commit into its marked version folder unless marked already; True if it built one."""
    folder = version_folder(layout, version_name(commit))
    before = version_state(layout, folder)
    match before:
        case VersionState.MARKED_NO_AGENT | VersionState.COMPLETE:
            return False
        case VersionState.ABSENT | VersionState.PARTIAL:
            _build(host, layout, commit, folder, before)
            return True
        case _:
            assert_never(before)


def _build(host: Host, layout: Layout, commit: str, folder: Path, before: VersionState) -> None:
    try:
        if before is VersionState.PARTIAL:
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        packages = host.build(commit, folder / VENV_FOLDER_NAME)
        (folder / PACKAGES_FILE_NAME).write_text(packages, encoding="utf-8")
        _marker(folder).write_text("")
        stepped(layout, folder, before)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise


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
