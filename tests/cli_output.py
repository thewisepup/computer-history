"""Reading command output: past the profile line every command starts with, and by section."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from computer_history.cli import app as cli_app
from computer_history.cli.status import LIVE_CHECKS_TITLE
from computer_history.host import Host
from computer_history.watchdog import Check


class RunCli(Protocol):
    """The run fixture: the CLI run from a code location, giving its exit code, out lines, err."""

    def __call__(
        self, code: Path, *argv: str, host: Host | None = None
    ) -> tuple[int, list[str], str]: ...


def after_profile_line(out: str) -> str:
    """The output after its first line, which must be the profile line."""
    first, _, rest = out.partition("\n")
    assert first.startswith("Profile "), out
    return rest


def run_here(run: RunCli, *argv: str) -> tuple[int, str, str]:
    """The CLI run from this checkout's own code, with its out lines joined back into one text."""
    code, out, err = run(cli_app.CODE_LOCATION, *argv)
    return code, "".join(f"{line}\n" for line in out), err


def status_out(run: RunCli, *argv: str) -> str:
    """Status run from this checkout, which must exit 0: its output past the profile line."""
    code, out, err = run_here(run, "status", *argv)
    assert code == 0, err
    return after_profile_line(out)


def ingest_line(out: list[str]) -> str:
    """Status's one Ingest line."""
    [line] = [line for line in out if line.startswith("Ingest:")]
    return line


def live_check(out: list[str], check: Check) -> str:
    """Status's line for one check the watchdog makes, judged as status ran."""
    [line] = [
        line for line in section(out, LIVE_CHECKS_TITLE) if line.startswith(f"  {check.value} ")
    ]
    return line


UNREACHABLE_AW = ("--aw-url", "http://127.0.0.1:1/api/0")
STATUS = ("status", *UNREACHABLE_AW)


def section(out: list[str], title: str) -> list[str]:
    """The indented lines under a section title in a command's output."""
    start = out.index(title) + 1
    end = next((i for i in range(start, len(out)) if not out[i].startswith("  ")), len(out))
    return out[start:end]
