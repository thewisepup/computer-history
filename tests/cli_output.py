"""Reading command output past the profile line every command starts with."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol


class RunCli(Protocol):
    """The run fixture: the CLI run from a code location, giving its exit code, out lines, err."""

    def __call__(self, code: Path, *argv: str) -> tuple[int, list[str], str]: ...


def after_profile_line(out: str) -> str:
    """The output after its first line, which must be the profile line."""
    first, _, rest = out.partition("\n")
    assert first.startswith("Profile "), out
    return rest
