"""The stable install: versions built from CI-gated commits, run by launchd at login.

    install.py        install (a current version, the PATH link, the LaunchAgents,
        |             the stopgap retired) and uninstall (all of it, never the data)
        |
    install_lock.py   the one lock on the live folder that install, uninstall,
        |             update, rollback and a stable restore hold while they run
        |
        +-- gate.py           the release gate: the checks a main commit must pass
        |                     (the capture agent's among them), and the walk to the
        |                     newest one that does
        +-- versions.py       build a commit into its marked version folder, noting what
        |                     its backend reads, and point current at it, undoing it all
        |                     on failure; the pointers
        +-- capture_agent.py  the installed agent's record, the agent app a version
        |                     folder carries (built when its source changed, else
        |                     copied), the installed app kept in the old version before
        |                     a swap, and whether rollback must move the agent back
        +-- launch_agents.py  the plists (kept running, run every minute, run daily or
        |                     once at login: the backend, the backup, the watchdog and
        |                     ActivityWatch), loading, stopping, starting and removing
        |                     them, and what
        |                     launchd says about each agent for status
        +-- stopped_agents.py the agents update and restore stop for a step, and
        |                     starting or reloading them after it, even when it fails
        +-- layout.py         where the versions, pointers, link, plists and logs live

    updates/          update (build the newest passing commit, back up, switch, wait
        |             for the backend's first ok cycle with spool deletion held, swap
        |             in a changed capture agent and wait for its first record, and
        |             fall back on its own) and rollback (current and previous swapped,
        |             the agent moved back when needed), one module per stage
        +-- update_log.py  one line per update, fallback, agent fallback, rollback and
                           agent move, read by status, which skips actions it doesn't know

    backups.py        the daily backup (seven kept) and the pre-update one beside the
                      database, the inventory status shows, and restore, which stops
                      and starts the backend, the watchdog and the daily backup around
                      it for the live database (uses stopped_agents.py and layout.py)

    agent_guard.py    whether the capture agent in a checkout may be installed by hand:
                      on main, clean, at origin/main, its gate checks passed, and the
                      stable backend at that commit or newer (uses gate.py, versions.py)

Everything that reaches launchctl, GitHub, git or uv goes through the host adapter it is given.
"""

from computer_history.stable.agent_guard import (
    GuardFailed,
    Unmet,
    check_agent_install,
)
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
from computer_history.stable.capture_agent import (
    InstalledAgent,
    installed_agent,
    record_installed_agent,
)
from computer_history.stable.gate import RELEASE_GATE
from computer_history.stable.install import InstallFailed, install, uninstall
from computer_history.stable.install_lock import InstallBusy, holding_install_lock
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
    NOTHING_CHANGED,
    PACKAGES_FILE_NAME,
    Layout,
    stable_layout,
)
from computer_history.stable.update_log import (
    AgentOutcome,
    UpdateAction,
    UpdateLogEntry,
    last_agent_fallback,
    last_update_log_entry,
)
from computer_history.stable.updates import (
    AGENT_ACTIVE_SECONDS,
    AGENT_WAIT_SECONDS,
    FIRST_CYCLE_WAIT_SECONDS,
    AgentCheck,
    RollbackFailed,
    UpdateFailed,
    UpdateReport,
    rollback,
    update,
)
from computer_history.stable.versions import InstalledVersion, pointed, version_name

__all__ = [
    "ACTIVITYWATCH_AT_LOGIN",
    "AGENT_ACTIVE_SECONDS",
    "AGENT_WAIT_SECONDS",
    "BACKEND",
    "BACKUPS_FOLDER_NAME",
    "CAPTURE_AGENT_LABEL",
    "DAILY_BACKUP",
    "DAILY_FOLDER_NAME",
    "DAILY_KEPT",
    "EVERY_MINUTE_SECONDS",
    "FIRST_CYCLE_WAIT_SECONDS",
    "LOAD_ATTEMPTS",
    "NOTHING_CHANGED",
    "PACKAGES_FILE_NAME",
    "PRE_UPDATE_FOLDER_NAME",
    "RELEASE_GATE",
    "RESTART_THROTTLE_SECONDS",
    "SET_ASIDE_FOLDER_NAME",
    "STABLE_AGENTS",
    "STOPGAP_LABEL",
    "TAKEN_AT_STAMP",
    "WATCHDOG",
    "AgentCheck",
    "AgentOutcome",
    "AgentStatus",
    "BackupFailed",
    "BackupInventory",
    "DailyOutcome",
    "GuardFailed",
    "InstallBusy",
    "InstallFailed",
    "InstalledAgent",
    "InstalledVersion",
    "LaunchAgent",
    "Layout",
    "RestoreFailed",
    "RollbackFailed",
    "Schedule",
    "Unmet",
    "UpdateAction",
    "UpdateFailed",
    "UpdateLogEntry",
    "UpdateReport",
    "agent_statuses",
    "backup_inventory",
    "check_agent_install",
    "daily_backup_path",
    "holding_install_lock",
    "install",
    "installed_agent",
    "last_agent_fallback",
    "last_update_log_entry",
    "pointed",
    "record_installed_agent",
    "restore_backup",
    "rollback",
    "stable_layout",
    "take_daily_backup",
    "take_pre_update_backup",
    "uninstall",
    "update",
    "version_name",
]
