from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from pathlib import Path
from typing import Protocol, cast

COMMAND_NAME = "computer-history"
SPOOL_READS_FLAG = "--spool-reads"
ACTIVITYWATCH_BUNDLE_ID = "net.activitywatch.ActivityWatch"
OPEN_ACTIVITYWATCH = ("/usr/bin/open", "-g", "-b", ACTIVITYWATCH_BUNDLE_ID)
ALERT_REPEAT = timedelta(hours=1)


class HostError(Exception):
    """A call to macOS or the network failed; the message says which and why."""


class JobBusy(HostError):
    """launchd is still busy with the job, as right after a boot-out; trying again may work."""


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


@dataclass(frozen=True)
class SpoolReads:
    """The spool version and record kinds a version's backend reads."""

    version: int
    kinds: tuple[str, ...]

    def as_json(self) -> str:
        return json.dumps({"spool_version": self.version, "kinds": list(self.kinds)})

    @classmethod
    def from_json(cls, text: str) -> SpoolReads:
        """Read what as_json wrote, raising ValueError for anything else."""
        found = json.loads(text)
        if not isinstance(found, dict):
            raise ValueError("not a JSON object")
        fields = cast(dict[str, object], found)
        version, kinds = fields.get("spool_version"), fields.get("kinds")
        if type(version) is not int or not isinstance(kinds, list):
            raise ValueError("no spool version and list of kinds")
        return cls(version, tuple(str(kind) for kind in cast(list[object], kinds)))


@dataclass(frozen=True)
class BackendBuild:
    """What building a version gave: its frozen packages and what its backend reads."""

    packages: str
    reads: SpoolReads


class Host(Protocol):
    """Everything that touches macOS or the network: launchctl, GitHub, uv, Swift and codesign,
    ActivityWatch's app and user notifications."""

    def main_commits(self, limit: int) -> list[str]:
        """The newest commits on main, newest first."""
        ...

    def check_runs(self, commit: str) -> list[CheckRun]:
        """The latest run of each CI check on a commit."""
        ...

    def build(self, commit: str, venv: Path) -> BackendBuild:
        """Build the commit into a new virtual environment and ask its command what it reads."""
        ...

    def agent_tree(self, commit: str) -> str:
        """The git tree hash of the capture agent's source folder at a commit."""
        ...

    def check_agent_toolchain(self) -> None:
        """Raise a HostError naming what the agent build lacks: Swift or the signing identity."""
        ...

    def build_agent(self, commit: str, app: Path) -> None:
        """Build and sign the capture agent from a fresh export of a commit, into the app path."""
        ...

    def install_agent(self, app: Path, fixed: Path) -> None:
        """Put an app over the agent's fixed path and register it, retrying until it runs."""
        ...

    def job(self, label: str) -> JobState:
        """The state of the LaunchAgent with this label in the login session."""
        ...

    def load(self, plist: Path) -> None:
        """Load a LaunchAgent from its plist into the login session.

        Raises JobBusy while launchd is still booting out an earlier copy.
        """
        ...

    def unload(self, label: str) -> None:
        """Boot a loaded LaunchAgent out of the login session, stopping its process."""
        ...

    def activitywatch_running(self) -> bool:
        """Whether the ActivityWatch app is running in this user's session."""
        ...

    def open_activitywatch(self) -> None:
        """Open the ActivityWatch app in the background."""
        ...

    def notify(self, message: str) -> None:
        """Post a user notification under the app's one title."""
        ...
