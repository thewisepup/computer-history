"""The stable install: versions built from CI-gated commits, run by launchd at login.

    install.py        install (a current version, the PATH link, the LaunchAgents,
        |             the stopgap retired) and uninstall (all of it, never the data)
        |
        +-- gate.py           the release gate: the checks a main commit must pass,
        |                     and the walk to the newest one that does
        +-- versions.py       build a commit into its marked version folder and point
        |                     current at it, undoing it all on failure; the pointers
        +-- launch_agents.py  the plists (kept running, run every minute, run daily or
        |                     once at login: the backend, the backup, the watchdog and
        |                     ActivityWatch), loading, stopping, starting and removing
        |                     them, and what
        |                     launchd says about each agent for status
        +-- layout.py         where the versions, pointers, link, plists and logs live

    updates.py        update (build the newest passing commit, back up, switch, wait
        |             for the backend's first cycle with spool deletion held, and fall
        |             back on its own) and rollback (current and previous swapped)
        +-- update_log.py  one line per update, fallback and rollback, read by status

    backups.py        the daily backup (seven kept) and the pre-update one beside the
                      database, the inventory status shows, and restore, which stops
                      and starts the backend and the daily backup around it for the
                      live database (uses launch_agents.py and layout.py)

Everything that reaches launchctl, GitHub or uv goes through the host adapter it is given.
"""

from computer_history.stable.backups import (
    BACKUPS_FOLDER_NAME,
    DAILY_FOLDER_NAME,
    DAILY_KEPT,
    PRE_UPDATE_FOLDER_NAME,
    SET_ASIDE_FOLDER_NAME,
    TAKEN_AT_STAMP,
    BackupFailed,
    BackupInventory,
    DailyOutcome,
    RestoreFailed,
    backup_inventory,
    daily_backup_path,
    restore_backup,
    take_daily_backup,
    take_pre_update_backup,
)
from computer_history.stable.gate import RELEASE_GATE
from computer_history.stable.install import InstallFailed, install, uninstall
from computer_history.stable.launch_agents import (
    ACTIVITYWATCH_AT_LOGIN,
    BACKEND,
    DAILY_BACKUP,
    EVERY_MINUTE_SECONDS,
    LOAD_ATTEMPTS,
    RESTART_THROTTLE_SECONDS,
    STABLE_AGENTS,
    STOPGAP_LABEL,
    WATCHDOG,
    AgentStatus,
    LaunchAgent,
    Schedule,
    agent_statuses,
)
from computer_history.stable.layout import (
    CAPTURE_AGENT_LABEL,
    PACKAGES_FILE_NAME,
    Layout,
    stable_layout,
)
from computer_history.stable.update_log import (
    UpdateAction,
    UpdateLogEntry,
    last_update_log_entry,
)
from computer_history.stable.updates import (
    RollbackFailed,
    UpdateFailed,
    UpdateOutcome,
    rollback,
    update,
)
from computer_history.stable.versions import pointed, version_name

__all__ = [
    "ACTIVITYWATCH_AT_LOGIN",
    "BACKEND",
    "BACKUPS_FOLDER_NAME",
    "CAPTURE_AGENT_LABEL",
    "DAILY_BACKUP",
    "DAILY_FOLDER_NAME",
    "DAILY_KEPT",
    "EVERY_MINUTE_SECONDS",
    "LOAD_ATTEMPTS",
    "PACKAGES_FILE_NAME",
    "PRE_UPDATE_FOLDER_NAME",
    "RELEASE_GATE",
    "RESTART_THROTTLE_SECONDS",
    "SET_ASIDE_FOLDER_NAME",
    "STABLE_AGENTS",
    "STOPGAP_LABEL",
    "TAKEN_AT_STAMP",
    "WATCHDOG",
    "AgentStatus",
    "BackupFailed",
    "BackupInventory",
    "DailyOutcome",
    "InstallFailed",
    "LaunchAgent",
    "Layout",
    "RestoreFailed",
    "RollbackFailed",
    "Schedule",
    "UpdateAction",
    "UpdateFailed",
    "UpdateLogEntry",
    "UpdateOutcome",
    "agent_statuses",
    "backup_inventory",
    "daily_backup_path",
    "install",
    "last_update_log_entry",
    "pointed",
    "restore_backup",
    "rollback",
    "stable_layout",
    "take_daily_backup",
    "take_pre_update_backup",
    "uninstall",
    "update",
    "version_name",
]
