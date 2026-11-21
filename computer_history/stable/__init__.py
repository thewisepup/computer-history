"""The stable install: versions built from CI-gated commits, run by launchd at login.

    install.py        install (a current version, the PATH link, the LaunchAgents,
        |             the stopgap retired) and uninstall (all of it, never the data)
        |
    backups.py        the daily backup (seven kept) and the pre-update one beside the
        |             database, what status lists, and restore, which stops and
        |             starts the backend around putting a backup in place
        |
        +-- gate.py           the release gate: the checks a main commit must pass,
        |                     and the walk to the newest one that does
        +-- versions.py       build a commit into its marked version folder and point
        |                     current at it, undoing it all on failure; the pointers
        +-- launch_agents.py  the plists (kept running, or run daily), loading,
        |                     stopping, starting and removing them, and what
        |                     launchd says about each agent for status
        +-- layout.py         where the versions, pointers, link, plists and logs live

Everything that reaches launchctl, GitHub or uv goes through the host adapter it is given.
"""

from computer_history.stable.backups import (
    DAILY_KEPT,
    BackendRestart,
    KeptBackups,
    RestoreFailed,
    find_daily_backup,
    kept_backups,
    restore_backup,
    take_daily_backup,
    take_pre_update_backup,
)
from computer_history.stable.gate import RELEASE_GATE
from computer_history.stable.install import InstallFailed, install, uninstall
from computer_history.stable.launch_agents import (
    BACKEND,
    DAILY_BACKUP,
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
    "DAILY_BACKUP",
    "DAILY_KEPT",
    "LOAD_ATTEMPTS",
    "PACKAGES_FILE_NAME",
    "RELEASE_GATE",
    "RESTART_THROTTLE_SECONDS",
    "STOPGAP_LABEL",
    "AgentStatus",
    "BackendRestart",
    "InstallFailed",
    "KeptBackups",
    "Layout",
    "RestoreFailed",
    "agent_statuses",
    "find_daily_backup",
    "install",
    "kept_backups",
    "pointed",
    "restore_backup",
    "stable_layout",
    "take_daily_backup",
    "take_pre_update_backup",
    "uninstall",
    "version_name",
]
