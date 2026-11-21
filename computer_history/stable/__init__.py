"""The stable install: versions built from CI-gated commits, run by launchd at login.

    install.py        install (a current version, the PATH link, the LaunchAgents,
        |             the stopgap retired) and uninstall (all of it, never the data)
        |
        +-- gate.py           the release gate: the checks a main commit must pass,
        |                     and the walk to the newest one that does
        +-- versions.py       build a commit into its marked version folder and point
        |                     current at it, undoing it all on failure; the pointers
        +-- launch_agents.py  the plists, loading and removing them, and what
        |                     launchd says about each agent for status
        +-- layout.py         where the versions, pointers, link, plists and logs live

Everything that reaches launchctl, GitHub or uv goes through the host adapter it is given.
"""

from computer_history.stable.gate import RELEASE_GATE
from computer_history.stable.install import InstallFailed, install, uninstall
from computer_history.stable.launch_agents import (
    BACKEND,
    LOAD_ATTEMPTS,
    RESTART_THROTTLE_SECONDS,
    STOPGAP_LABEL,
    AgentStatus,
    agent_statuses,
)
from computer_history.stable.layout import (
    CAPTURE_AGENT_LABEL,
    PACKAGES_FILE_NAME,
    Layout,
    stable_layout,
)
from computer_history.stable.versions import pointed, version_name

__all__ = [
    "BACKEND",
    "CAPTURE_AGENT_LABEL",
    "LOAD_ATTEMPTS",
    "PACKAGES_FILE_NAME",
    "RELEASE_GATE",
    "RESTART_THROTTLE_SECONDS",
    "STOPGAP_LABEL",
    "AgentStatus",
    "InstallFailed",
    "Layout",
    "agent_statuses",
    "install",
    "pointed",
    "stable_layout",
    "uninstall",
    "version_name",
]
