"""The spool folder's finished files: list them oldest first, read, remove or set one aside."""

from __future__ import annotations

import os
from pathlib import Path

from computer_history.sources.contract import SourceUnavailable

OPEN_FILE = "open.part"
FINISHED_SUFFIX = ".jsonl"
FINISHED_NAME_FORMAT = "%Y%m%dT%H%M%S.%fZ"
UNREADABLE_FOLDER = "unreadable"


class SpoolError(SourceUnavailable):
    """The spool folder could not be listed or changed."""


def finished_files(folder: Path) -> list[Path]:
    """The spool's finished files, oldest first by name, or none if the folder does not exist."""
    try:
        with os.scandir(folder) as entries:
            names = sorted(
                entry.name
                for entry in entries
                if entry.name.endswith(FINISHED_SUFFIX)
                and not entry.name.startswith(".")
                and entry.is_file(follow_symlinks=False)
            )
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise SpoolError(f"cannot list the spool at {folder}: {exc}") from exc
    return [folder / name for name in names]


def read_lines(path: Path) -> list[bytes]:
    """The file's lines without their line endings."""
    lines = path.read_bytes().split(b"\n")
    if lines and not lines[-1]:
        lines.pop()
    return lines


def remove_finished(path: Path) -> None:
    """Delete a finished file once it is stored."""
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise SpoolError(f"cannot remove stored spool file {path}: {exc}") from exc


def set_aside(path: Path) -> Path | None:
    """Move a file into the spool's unreadable folder under a name no other file there has.

    Returns where it went, or None if the file was already gone.
    """
    folder = path.parent / UNREADABLE_FOLDER
    target = folder / path.name
    copy = 0
    try:
        folder.mkdir(exist_ok=True)
        while True:
            try:
                os.link(path, target)
                break
            except FileExistsError:
                copy += 1
                target = folder / f"{path.stem}.{copy}{path.suffix}"
        path.unlink(missing_ok=True)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise SpoolError(f"cannot move spool file {path} aside: {exc}") from exc
    return target
