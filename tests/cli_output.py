"""Running the CLI in process, and reading its output past the profile line it starts with."""

from __future__ import annotations

from pathlib import Path

import pytest

from computer_history import cli
from computer_history.host import Host


def run_cli(
    capsys: pytest.CaptureFixture[str], code: Path, *argv: str, host: Host | None = None
) -> tuple[int, list[str], str]:
    """Run one command as code at this location would: its exit code, output lines and errors."""
    exit_code = cli.main(list(argv), code=code, host=host)
    captured = capsys.readouterr()
    return exit_code, captured.out.splitlines(), captured.err


def after_profile_line(out: str) -> str:
    """The output after its first line, which must be the profile line."""
    first, _, rest = out.partition("\n")
    assert first.startswith("Profile "), out
    return rest
