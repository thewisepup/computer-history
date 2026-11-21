from __future__ import annotations

import argparse
import os
import sys

from computer_history.stable import (
    RELEASE_GATE,
    RESTART_THROTTLE_SECONDS,
    STOPGAP_LABEL,
    InstallFailed,
    install,
    stable_layout,
    uninstall,
    version_name,
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
        print(f"Release gate: {', '.join(RELEASE_GATE)}")
        for verdict in report.skipped:
            print(f"  skipped {version_name(verdict.commit)}: {verdict.summary}")
        print(f"Installed version {report.version} (commit {report.built})")
    print(f"  current       {layout.current} -> {layout.versions / report.version}")
    print(f"  PATH link     {layout.link} -> {layout.command(layout.current)}")
    if report.retired_stopgap:
        print(f"  stopgap       {STOPGAP_LABEL} booted out and removed")
    for agent in report.loaded:
        if agent.daily_at is None:
            runs = f"restarted by launchd at most every {RESTART_THROTTLE_SECONDS}s"
        else:
            runs = f"daily at {agent.daily_at:%H:%M} and at login"
        print(
            f"  LaunchAgent   {agent.label} loaded: computer-history {' '.join(agent.arguments)},"
            f" {runs}"
        )
    if not report.link_on_path:
        print(f"  note: {layout.link.parent} is not on PATH; add it to run computer-history")
    return 0


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
