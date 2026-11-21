from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from computer_history.host import COMMAND_NAME
from computer_history.store import VERSIONS_FOLDER_NAME, live_folder

CURRENT_POINTER_NAME = "current"
PREVIOUS_POINTER_NAME = "previous"
VENV_FOLDER_NAME = "venv"
PACKAGES_FILE_NAME = "packages.txt"
LABEL_PREFIX = "io.github.thewisepup.computer-history"
CAPTURE_AGENT_LABEL = f"{LABEL_PREFIX}.agent"
CAPTURE_AGENT_APP = "ComputerHistoryAgent.app"


@dataclass(frozen=True)
class Layout:
    """Where the stable install keeps its versions, pointers, PATH link, LaunchAgents and logs."""

    live: Path
    home: Path

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
    def link(self) -> Path:
        return self.home / ".local" / "bin" / COMMAND_NAME

    @property
    def launch_agents(self) -> Path:
        return self.home / "Library" / "LaunchAgents"

    @property
    def capture_agent_plist(self) -> Path:
        """The capture agent's plist, inside the app bundle its own install script puts in place."""
        bundle = self.home / "Applications" / CAPTURE_AGENT_APP
        return bundle / "Contents" / "Library" / "LaunchAgents" / f"{CAPTURE_AGENT_LABEL}.plist"

    @property
    def logs(self) -> Path:
        return self.home / "Library" / "Logs" / COMMAND_NAME

    def command(self, version: Path) -> Path:
        """The computer-history command inside a version folder, or through a pointer to one."""
        return version / VENV_FOLDER_NAME / "bin" / COMMAND_NAME


def stable_layout() -> Layout:
    """The stable install's layout for the current user's home and live folder."""
    return Layout(live=live_folder(), home=Path.home())
