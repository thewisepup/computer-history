from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from computer_history.host import COMMAND_NAME
from computer_history.logs import LOG_FOLDER_NAME
from computer_history.store import DATABASE_NAME, VERSIONS_FOLDER_NAME, live_folder

NOTHING_CHANGED = "nothing was changed"
CURRENT_POINTER_NAME = "current"
PREVIOUS_POINTER_NAME = "previous"
VENV_FOLDER_NAME = "venv"
PACKAGES_FILE_NAME = "packages.txt"
UPDATE_LOG_NAME = "update-log.jsonl"
LABEL_PREFIX = "io.github.thewisepup.computer-history"
CAPTURE_AGENT_LABEL = f"{LABEL_PREFIX}.agent"
CAPTURE_AGENT_APP = "ComputerHistoryAgent.app"
FELL_BACK_AGENT_APP = "ComputerHistoryAgent.fell-back.app"
AGENT_COMMIT_NAME = "agent-commit.txt"
FELL_BACK_AGENT_COMMIT_NAME = "agent-commit.fell-back.txt"
INSTALLED_AGENT_NAME = "installed-agent.json"


@dataclass(frozen=True)
class Layout:
    """Where the stable install keeps its versions, pointers, update log, PATH link, LaunchAgents
    and logs."""

    live: Path
    home: Path

    @property
    def database(self) -> Path:
        return self.live / DATABASE_NAME

    @property
    def versions(self) -> Path:
        return self.live / VERSIONS_FOLDER_NAME

    @property
    def current(self) -> Path:
        return self.live / CURRENT_POINTER_NAME

    @property
    def previous(self) -> Path:
        return self.live / PREVIOUS_POINTER_NAME

    @property
    def update_log(self) -> Path:
        return self.live / UPDATE_LOG_NAME

    @property
    def link(self) -> Path:
        return self.home / ".local" / "bin" / COMMAND_NAME

    @property
    def launch_agents(self) -> Path:
        return self.home / "Library" / "LaunchAgents"

    @property
    def installed_agent(self) -> Path:
        """The record of which commit the app at the capture agent's fixed path was built from."""
        return self.live / INSTALLED_AGENT_NAME

    @property
    def capture_agent_app(self) -> Path:
        """The one fixed path the running capture agent's app is installed and registered at."""
        return self.home / "Applications" / CAPTURE_AGENT_APP

    @property
    def capture_agent_plist(self) -> Path:
        """The capture agent's plist, inside the app bundle at its fixed path."""
        bundle = self.capture_agent_app
        return bundle / "Contents" / "Library" / "LaunchAgents" / f"{CAPTURE_AGENT_LABEL}.plist"

    @property
    def logs(self) -> Path:
        return self.home / "Library" / "Logs" / LOG_FOLDER_NAME

    def command(self, version: Path) -> Path:
        """The computer-history command inside a version folder, or through a pointer to one."""
        return version / VENV_FOLDER_NAME / "bin" / COMMAND_NAME

    def agent_app(self, version: Path) -> Path:
        """The copy of the capture agent's app a version folder carries."""
        return version / CAPTURE_AGENT_APP

    def agent_commit(self, version: Path) -> Path:
        """The note of the commit a version folder's agent app was built from."""
        return version / AGENT_COMMIT_NAME

    def fell_back_agent_app(self, version: Path) -> Path:
        """Where a version folder keeps its agent build after it fell back."""
        return version / FELL_BACK_AGENT_APP

    def fell_back_agent_commit(self, version: Path) -> Path:
        """The note of the commit the build that fell back was built from."""
        return version / FELL_BACK_AGENT_COMMIT_NAME


def stable_layout() -> Layout:
    """The stable install's layout for the current user's home and live folder."""
    return Layout(live=live_folder(), home=Path.home())
