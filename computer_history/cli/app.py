from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TextIO

import computer_history
from computer_history.cli.agent_guard import cmd_check_agent_install
from computer_history.cli.backfill import cmd_backfill
from computer_history.cli.backup import backup_arg, cmd_backup, cmd_restore
from computer_history.cli.dev import add_dev_commands, cmd_dev
from computer_history.cli.ingest import cmd_ingest
from computer_history.cli.install import cmd_install, cmd_uninstall
from computer_history.cli.logs import cmd_logs
from computer_history.cli.profile import profile_line
from computer_history.cli.rebuild import cmd_rebuild_signals
from computer_history.cli.status import cmd_status
from computer_history.cli.update import cmd_rollback, cmd_update
from computer_history.cli.watchdog import cmd_watchdog
from computer_history.host import Host, LiveHost
from computer_history.logs import LEVEL_NAMES, configure, resolve_level, resolve_log_dir
from computer_history.sources import POLL_INTERVAL_SECONDS
from computer_history.sources.activitywatch import DEFAULT_AW_URL
from computer_history.sources.capture_spool import RECORD_KINDS, SPOOL_ENV_VAR, SPOOL_VERSION
from computer_history.stable import (
    FIRST_CYCLE_WAIT_SECONDS,
    InstallBusy,
    holding_install_lock,
    stable_layout,
)
from computer_history.store import (
    DATABASE_NAME,
    DB_ENV_VAR,
    DEV_FOLDER_NAME,
    LIVE_FOLDER_NAME,
    LiveDatabaseRefused,
    Profile,
    live_folder,
    resolve_db_path,
    resolve_dev_db_path,
    running_code,
)

CODE_LOCATION = Path(computer_history.__file__).resolve().parent
DATABASE_COMMANDS = frozenset(
    {"ingest", "status", "rebuild-signals", "backfill", "backup", "restore", "watchdog"}
)
INSTALL_COMMANDS = frozenset({"install", "uninstall", "update", "rollback"})
READS_THE_INSTALL = INSTALL_COMMANDS | {"check-agent-install"}

COMMANDS = {
    "ingest": "Ingest settled ActivityWatch events and the capture spool into the store.",
    "status": "Show store and source status.",
    "rebuild-signals": (
        "Rebuild derived signals from stored observations (blocks ingest while running)."
    ),
    "backfill": (
        "One-time ingest of existing ActivityWatch history, in bounded chunks"
        " (idempotent: re-running adds nothing)."
    ),
    "backup": (
        "Take today's backup of the database into the backups folder beside it, checked for"
        " integrity, keeping the newest seven days (run daily by the stable install)."
    ),
    "restore": (
        "Put a backup in the database's place: the stable install stops its backend first and"
        " starts it again after. The current database is set aside, never deleted."
    ),
    "update": (
        "Move the stable install to the newest main commit that passed the release gate: back"
        " up the database, restart the backend on it, and fall back on its own if its first"
        " ingest cycle does not complete; then swap in a changed capture agent and put the old"
        " one back if it records nothing while you are active."
    ),
    "rollback": "Switch the stable install back to its previous version (no network needed).",
    "install": (
        "Set up the stable install from the newest main commit that passed the release gate,"
        " and start the backend at login from it (safe to re-run)."
    ),
    "uninstall": "Remove the stable install, its LaunchAgents and PATH link; keep the data.",
    "check-agent-install": (
        "Refuse to install the capture agent from this checkout by hand unless it is on main,"
        " clean, at origin/main, its capture-agent checks passed in CI, and the stable backend"
        " is at that commit or newer (run by the agent's install script; changes nothing)."
    ),
    "watchdog": (
        "Check once that the capture agent, ActivityWatch and the backend are recording, post a"
        " notification for a problem or a cleared one, and reopen ActivityWatch if it is down"
        " (run every minute by its LaunchAgent)."
    ),
    "dev": (
        "Developer tools: build-db makes a database of synthetic history, snapshot copies the"
        " live database into the dev folder, perf runs the performance gate, bench times each"
        " operation."
    ),
    "logs": "Show the JSON log's records, filtered by time, level, run or logger.",
}

log = logging.getLogger(__name__)

HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "ingest": cmd_ingest,
    "status": cmd_status,
    "rebuild-signals": cmd_rebuild_signals,
    "backfill": cmd_backfill,
    "backup": cmd_backup,
    "restore": cmd_restore,
    "update": cmd_update,
    "rollback": cmd_rollback,
    "install": cmd_install,
    "uninstall": cmd_uninstall,
    "check-agent-install": cmd_check_agent_install,
    "watchdog": cmd_watchdog,
    "dev": cmd_dev,
    "logs": cmd_logs,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="computer-history",
        description="Local activity store and ActivityWatch ingest.",
    )
    db_help = (
        f"SQLite database path (default: ${DB_ENV_VAR}, else {DATABASE_NAME} in the profile's"
        f" data folder: ~/Library/Application Support/{DEV_FOLDER_NAME}/ for dev,"
        f" {LIVE_FOLDER_NAME}/ for stable). For dev snapshot it is where the copy goes, always"
        " dev's database whichever profile runs"
    )
    parser.add_argument("--db-path", help=db_help)
    parser.add_argument(
        "--spool-reads",
        action=PrintSpoolReads,
        nargs=0,
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--log-level",
        type=str.upper,
        choices=LEVEL_NAMES,
        help="lowest level logged, to stderr and the log file (default:"
        " $COMPUTER_HISTORY_LOG_LEVEL, else INFO to the file and, except for ingest --watch,"
        " WARNING to stderr)",
    )
    db_after_command = argparse.ArgumentParser(add_help=False)
    db_after_command.add_argument("--db-path", default=argparse.SUPPRESS, help=db_help)
    aw = argparse.ArgumentParser(add_help=False)
    aw.add_argument(
        "--aw-url",
        default=DEFAULT_AW_URL,
        help=f"ActivityWatch API base URL (default: {DEFAULT_AW_URL})",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in COMMANDS.items():
        if name == "dev":
            add_dev_commands(subparsers.add_parser(name, help=help_text, description=help_text))
            continue
        if name == "logs":
            add_logs_arguments(subparsers.add_parser(name, help=help_text, description=help_text))
            continue
        if name in ("ingest", "status", "backfill", "watchdog"):
            parents = [db_after_command, aw]
        elif name == "update":
            parents = [aw]
        elif name in READS_THE_INSTALL:
            parents = []
        else:
            parents = [db_after_command]
        sub = subparsers.add_parser(name, help=help_text, description=help_text, parents=parents)
        if name == "rebuild-signals":
            sub.add_argument(
                "--allow-shrink",
                action="store_true",
                help="allow a rebuild that drops more than half of the existing signals"
                " (refused by default as a likely mapping bug)",
            )
        if name == "update":
            sub.add_argument(
                "--wait",
                type=float,
                default=FIRST_CYCLE_WAIT_SECONDS,
                metavar="SECONDS",
                help="how long to wait for the backend's first ingest cycle on the new version"
                f" before falling back (default: {FIRST_CYCLE_WAIT_SECONDS:g}; a long migration"
                " needs more)",
            )
        if name == "check-agent-install":
            sub.add_argument(
                "--force",
                action="store_true",
                help="allow the install even when conditions are unmet, listing each one skipped",
            )
        if name == "restore":
            sub.add_argument(
                "backup",
                type=backup_arg,
                help="the day of a daily backup (YYYY-MM-DD), or the path of a backup or a"
                " set-aside database",
            )
        if name == "backfill":
            sub.add_argument(
                "--start",
                type=when_arg,
                help="backfill from this ISO date/datetime (local time unless it has an"
                " offset) instead of where the ActivityWatch buckets begin",
            )
            sub.add_argument(
                "--end",
                type=when_arg,
                help="stop at this ISO date/datetime (default: the time the source's ingest"
                " is settled until, or now; never later than those)",
            )
            sub.add_argument(
                "--dry-run",
                action="store_true",
                help="discover sources and print the planned chunks; write nothing",
            )
        if name in ("ingest", "status", "watchdog"):
            sub.add_argument(
                "--spool-path",
                help=f"capture spool folder (default: ${SPOOL_ENV_VAR}, else spool/ beside"
                " the database)",
            )
        if name == "ingest":
            sub.add_argument(
                "--watch",
                action="store_true",
                help=f"poll every {POLL_INTERVAL_SECONDS}s until interrupted (Ctrl-C)",
            )
    return parser


class PrintSpoolReads(argparse.Action):
    """Answer the question stable versions built before rollback stopped moving the capture agent
    ask of every version they build, so they can still update to this one."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: object,
        option_string: str | None = None,
    ) -> None:
        print(json.dumps({"spool_version": SPOOL_VERSION, "kinds": list(RECORD_KINDS)}))
        parser.exit()


def add_logs_arguments(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--since",
        type=since_arg,
        help="only records from this long ago (30m, 2h, 1d) or this ISO date/datetime on",
    )
    sub.add_argument(
        "--level",
        type=str.lower,
        choices=[name.lower() for name in LEVEL_NAMES],
        default="debug",
        help="only records at this level or above (default: every record)",
    )
    sub.add_argument("--run", help="only records of this run id")
    sub.add_argument(
        "--logger",
        help="only records from this logger or below it (ingest, sources.activitywatch, ...)",
    )
    sub.add_argument("--json", action="store_true", help="print the raw JSON lines")


SINCE_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def since_arg(value: str) -> datetime:
    """A time that many seconds, minutes, hours or days ago (30m, 2h, 1d), or an ISO time."""
    amount, unit = value[:-1], value[-1:].lower()
    if unit in SINCE_UNITS and amount.isdigit():
        return datetime.now(UTC) - timedelta(seconds=int(amount) * SINCE_UNITS[unit])
    return when_arg(value)


def when_arg(value: str) -> datetime:
    """An ISO date or datetime. Local time unless it carries an offset."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"not an ISO date or datetime: {value!r} (e.g. 2026-11-01 or 2026-11-01T09:00)"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(UTC)


def main(
    argv: Sequence[str] | None = None, *, code: Path = CODE_LOCATION, host: Host | None = None
) -> int:
    """Run one command; the profile is decided from where the code runs."""
    args = build_parser().parse_args(argv)
    try:
        level = resolve_level(args.log_level)
    except ValueError as exc:
        print(f"computer-history: {exc}", file=sys.stderr)
        return 2
    running = running_code(code)
    args.profile = running.profile
    args.log_dir = resolve_log_dir(dev=running.profile is Profile.DEV)
    watching = getattr(args, "watch", False)
    configure(
        f"{args.command} --watch" if watching else args.command,
        level=level,
        long_running=watching,
        log_dir=args.log_dir,
    )
    args.host = LiveHost() if host is None else host
    args.code = code
    handler = HANDLERS.get(args.command)
    if handler is None:
        print(f"computer-history {args.command}: not implemented yet", file=sys.stderr)
        return 1
    uses = None
    try:
        args.database = _database(args)
    except LiveDatabaseRefused as exc:
        print(profile_line(running, code, "database refused"), flush=True)
        return _refused(exc)
    if args.database is not None:
        uses = f"database {args.database}"
    elif args.command in READS_THE_INSTALL:
        uses = f"stable install {live_folder()}"
    elif args.command == "dev" and args.dev_command == "build-db":
        uses = f"output {args.out}"
    print(profile_line(running, code, uses), file=_profile_stream(args.command), flush=True)
    try:
        if not _changes_the_install(args):
            return handler(args)
        with holding_install_lock(stable_layout()):
            return handler(args)
    except InstallBusy as exc:
        print(f"{args.command} refused: {exc}", file=sys.stderr)
        return 1
    except LiveDatabaseRefused as exc:
        return _refused(exc)
    except Exception:
        log.critical("command crashed", exc_info=True)
        return 1


def _changes_the_install(args: argparse.Namespace) -> bool:
    """Whether the command changes the stable install, or restores a database a stable run uses."""
    if args.command == "restore":
        return args.profile is Profile.STABLE
    return args.command in INSTALL_COMMANDS


def _database(args: argparse.Namespace) -> Path | None:
    """The database the command opens or copies into, or None for one that uses none."""
    if args.command in DATABASE_COMMANDS:
        return resolve_db_path(args.db_path, args.profile)
    if args.command == "dev" and args.dev_command == "snapshot":
        return resolve_dev_db_path(args.db_path)
    return None


def _profile_stream(command: str) -> TextIO:
    """stderr for logs, whose stdout is the records themselves (raw JSON lines with --json)."""
    return sys.stderr if command == "logs" else sys.stdout


def _refused(exc: LiveDatabaseRefused) -> int:
    print(f"refused: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
