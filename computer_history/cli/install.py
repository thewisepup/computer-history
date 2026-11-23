from __future__ import annotations

import argparse
import os
import sys

from computer_history.cli.formatting import release_gate_lines
from computer_history.host import COMMAND_NAME
from computer_history.stable import (
    EVERY_MINUTE_SECONDS,
    RESTART_THROTTLE_SECONDS,
    STOPGAP_LABEL,
    InstallFailed,
    LaunchAgent,
    Schedule,
    install,
    stable_layout,
    uninstall,
)


def cmd_install(args: argparse.Namespace) -> int:
    layout = stable_layout()
    try:
        report = install(args.host, layout, path=os.environ.get("PATH", ""))
    except InstallFailed as exc:
        print(f"install failed: {exc}", file=sys.stderr)
        return 1
    if report.built is None:
        print(f"Version {report.version} is already installed and current")
    else:
        for line in release_gate_lines(report.skipped):
            print(line)
        print(f"Installed version {report.version} (commit {report.built})")
    print(f"  current       {layout.current} -> {layout.versions / report.version}")
    print(f"  PATH link     {layout.link} -> {layout.command(layout.current)}")
    if report.retired_stopgap:
        print(f"  stopgap       {STOPGAP_LABEL} booted out and removed")
    for agent in report.loaded:
        print(f"  LaunchAgent   {agent.label} loaded: {_runs(agent)}")
    if not report.link_on_path:
        print(f"  note: {layout.link.parent} is not on PATH; add it to run computer-history")
    return 0


def _runs(agent: LaunchAgent) -> str:
    command = " ".join(agent.program or (COMMAND_NAME, *agent.arguments))
    match agent.schedule:
        case Schedule.KEEP_ALIVE:
            return f"{command}, restarted by launchd at most every {RESTART_THROTTLE_SECONDS}s"
        case Schedule.EVERY_MINUTE:
            return f"{command}, every {EVERY_MINUTE_SECONDS}s"
        case Schedule.DAILY:
            return f"{command}, daily at {agent.daily_at:%H:%M} and at login"
        case Schedule.AT_LOAD:
            return f"{command}, once at login"


def cmd_uninstall(args: argparse.Namespace) -> int:
    layout = stable_layout()
    try:
        report = uninstall(args.host, layout)
    except InstallFailed as exc:
        print(f"uninstall failed: {exc}", file=sys.stderr)
        return 1
    if not report.removed:
        print("Nothing to remove: the stable install is not set up")
    for path in report.removed:
        print(f"  removed       {path}")
    print(f"Kept the data in {layout.live}")
    return 0
