"""The stable install: versions built from CI-gated commits, run by launchd at login.

    install.py        install (a current version, the PATH link, the LaunchAgents,
        |             the stopgap retired) and uninstall (all of it, never the data)
        |
        +-- gate.py           the release gate: the checks a main commit must pass,
        |                     and the walk to the newest one that does
        +-- versions.py       build a commit into its marked version folder,
        |                     and the current and previous pointers
        +-- launch_agents.py  the plists, loading and removing them, and what
        |                     launchd says about each agent for status
        +-- layout.py         where the versions, pointers, link, plists and logs live

Everything that reaches launchctl, GitHub or uv goes through the host adapter it is given.
"""

from computer_history.stable.gate import (
    COMMITS_SEARCHED,
    RELEASE_GATE,
    GateSearch,
    GateVerdict,
    gate_verdict,
    newest_passing,
)
from computer_history.stable.install import (
    InstallFailed,
    InstallReport,
    UninstallReport,
    install,
    uninstall,
)
from computer_history.stable.launch_agents import (
    BACKEND,
    CAPTURE_AGENT_LABEL,
    RESTART_THROTTLE_SECONDS,
    STABLE_AGENTS,
    STOPGAP_LABEL,
    AgentStatus,
    LaunchAgent,
    agent_statuses,
)
from computer_history.stable.layout import PACKAGES_FILE_NAME, Layout, stable_layout
from computer_history.stable.versions import InstalledVersion, pointed

__all__ = [
    "BACKEND",
    "CAPTURE_AGENT_LABEL",
    "COMMITS_SEARCHED",
    "PACKAGES_FILE_NAME",
    "RELEASE_GATE",
    "RESTART_THROTTLE_SECONDS",
    "STABLE_AGENTS",
    "STOPGAP_LABEL",
    "AgentStatus",
    "GateSearch",
    "GateVerdict",
    "InstallFailed",
    "InstallReport",
    "InstalledVersion",
    "LaunchAgent",
    "Layout",
    "UninstallReport",
    "agent_statuses",
    "gate_verdict",
    "install",
    "newest_passing",
    "pointed",
    "stable_layout",
    "uninstall",
]
