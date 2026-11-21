from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any, cast

from computer_history.host.contract import (
    COMMAND_NAME,
    CheckOutcome,
    CheckRun,
    HostError,
    JobState,
)

REPO = "thewisepup/computer-history"
GITHUB_API = f"https://api.github.com/repos/{REPO}"
REPO_GIT_URL = f"https://github.com/{REPO}"
GITHUB_TIMEOUT_SECONDS = 15
CHECK_RUNS_PAGE = 100
PYTHON_VERSION = "3.12"
LAUNCHCTL = "/bin/launchctl"
COMMAND_TIMEOUT_SECONDS = 600
RUNNING_STATE = re.compile(r"^\s*state = running\s*$", re.MULTILINE)
PID_LINE = re.compile(r"^\s*pid = (\d+)\s*$", re.MULTILINE)


class LiveHost:
    """The host adapter for this Mac: launchctl in the login session, GitHub's public API, uv."""

    def main_commits(self, limit: int) -> list[str]:
        commits = cast(list[dict[str, Any]], _github(f"/commits?sha=main&per_page={limit}"))
        return [str(commit["sha"]) for commit in commits]

    def check_runs(self, commit: str) -> list[CheckRun]:
        found = cast(
            dict[str, Any], _github(f"/commits/{commit}/check-runs?per_page={CHECK_RUNS_PAGE}")
        )
        runs = cast(list[dict[str, Any]], found["check_runs"])
        return [CheckRun(str(run["name"]), _outcome(run)) for run in runs]

    def build(self, commit: str, venv: Path) -> str:
        uv = shutil.which("uv")
        if uv is None:
            raise HostError("uv is not installed (install it with `brew install uv`)")
        python = str(venv / "bin" / "python")
        _run(
            [
                uv,
                "venv",
                "--python",
                PYTHON_VERSION,
                "--python-preference",
                "only-managed",
                str(venv),
            ],
            "create the virtual environment",
        )
        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                python,
                f"{COMMAND_NAME} @ git+{REPO_GIT_URL}@{commit}",
            ],
            f"install commit {commit}",
        )
        _run([str(venv / "bin" / COMMAND_NAME), "--help"], "run the built command")
        return _run([uv, "pip", "freeze", "--python", python], "list the installed packages")

    def job(self, label: str) -> JobState:
        try:
            shown = subprocess.run(
                [LAUNCHCTL, "print", f"{_domain()}/{label}"],
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HostError(f"could not ask launchctl about {label}: {exc}") from exc
        if shown.returncode != 0:
            return JobState(loaded=False)
        pid = PID_LINE.search(shown.stdout) if RUNNING_STATE.search(shown.stdout) else None
        return JobState(loaded=True, pid=int(pid.group(1)) if pid else None)

    def load(self, plist: Path) -> None:
        _run([LAUNCHCTL, "bootstrap", _domain(), str(plist)], f"load {plist}")

    def unload(self, label: str) -> None:
        _run([LAUNCHCTL, "bootout", f"{_domain()}/{label}"], f"boot out {label}")


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _outcome(run: dict[str, Any]) -> CheckOutcome:
    if run.get("status") != "completed":
        return CheckOutcome.RUNNING
    match run.get("conclusion"):
        case "success":
            return CheckOutcome.SUCCESS
        case "cancelled":
            return CheckOutcome.CANCELLED
        case _:
            return CheckOutcome.FAILURE


def _github(path: str) -> object:
    request = urllib.request.Request(
        GITHUB_API + path,
        headers={"Accept": "application/vnd.github+json", "User-Agent": COMMAND_NAME},
    )
    try:
        with urllib.request.urlopen(request, timeout=GITHUB_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except (OSError, ValueError) as exc:
        raise HostError(f"could not read {REPO}'s checks from GitHub: {exc}") from exc


def _run(command: list[str], doing: str) -> str:
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, timeout=COMMAND_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostError(f"could not {doing}: {exc}") from exc
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()
        raise HostError(f"could not {doing}: {detail[-1] if detail else done.returncode}")
    return done.stdout
