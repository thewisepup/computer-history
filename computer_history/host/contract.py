from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

COMMAND_NAME = "computer-history"


class HostError(Exception):
    """A call to macOS or the network failed; the message says which and why."""


class CheckOutcome(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    RUNNING = "running"


@dataclass(frozen=True)
class CheckRun:
    """One CI check's latest run on a commit."""

    name: str
    outcome: CheckOutcome


@dataclass(frozen=True)
class JobState:
    """What launchd says about a LaunchAgent: whether it is loaded, and its process if running."""

    loaded: bool
    pid: int | None = None


class Host(Protocol):
    """Everything that touches macOS or the network: launchctl, GitHub and building with uv."""

    def main_commits(self, limit: int) -> list[str]:
        """The newest commits on main, newest first."""
        ...

    def check_runs(self, commit: str) -> list[CheckRun]:
        """The latest run of each CI check on a commit."""
        ...

    def build(self, commit: str, venv: Path) -> str:
        """Build the commit into a new virtual environment, smoke it, and return its packages."""
        ...

    def job(self, label: str) -> JobState:
        """The state of the LaunchAgent with this label in the login session."""
        ...

    def load(self, plist: Path) -> None:
        """Load a LaunchAgent from its plist into the login session."""
        ...

    def unload(self, label: str) -> None:
        """Boot a loaded LaunchAgent out of the login session, stopping its process."""
        ...
