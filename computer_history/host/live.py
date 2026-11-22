from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from computer_history.host.contract import (
    COMMAND_NAME,
    OPEN_ACTIVITYWATCH,
    CheckOutcome,
    CheckRun,
    GitState,
    HostError,
    JobBusy,
    JobState,
)

REPO = "thewisepup/computer-history"
GITHUB_API = f"https://api.github.com/repos/{REPO}"
REPO_GIT_URL = f"https://github.com/{REPO}"
GITHUB_TOKEN_ENV_VAR = "GITHUB_TOKEN"
GITHUB_TIMEOUT_SECONDS = 15
CHECK_RUNS_PAGE = 100
RATE_LIMITED_STATUSES = frozenset({403, 429})
PYTHON_VERSION = "3.12"
GIT_REF_MISSING = 1
ORIGIN_MAIN_REF = "refs/remotes/origin/main"
GIT_LOCATION_VARS = frozenset({"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"})
LAUNCHCTL = "/bin/launchctl"
LAUNCHCTL_BUSY_CODES = frozenset({5, 37})  # EIO, EALREADY: a boot-out still in progress
LAUNCHCTL_NO_SUCH_SERVICE = 113
COMMAND_TIMEOUT_SECONDS = 600
QUICK_COMMAND_TIMEOUT_SECONDS = 10
RUNNING_STATE = re.compile(r"^\s*state = running\s*$", re.MULTILINE)
PID_LINE = re.compile(r"^\s*pid = (\d+)\s*$", re.MULTILINE)
PGREP = "/usr/bin/pgrep"
PGREP_NONE_FOUND = 1
ACTIVITYWATCH_PROCESS = "aw-qt"
OSASCRIPT = "/usr/bin/osascript"
NOTIFY_ENV_VAR = "COMPUTER_HISTORY_NOTIFY"
NOTIFICATION_TITLE = "Computer History"
NOTIFY_SCRIPT = (
    "on run argv",
    "display notification (item 2 of argv) with title (item 1 of argv)",
    "end run",
)


class LiveHost:
    """The host adapter for this Mac: launchctl in the login session, GitHub's API, uv, pgrep,
    open and osascript (off when $COMPUTER_HISTORY_NOTIFY is 0)."""

    def main_commits(self, limit: int) -> list[str]:
        commits = _github(f"/commits?sha=main&per_page={limit}", "list main's newest commits")
        return [str(commit["sha"]) for commit in cast(list[dict[str, Any]], commits)]

    def check_runs(self, commit: str) -> list[CheckRun]:
        found = _github(
            f"/commits/{commit}/check-runs?per_page={CHECK_RUNS_PAGE}",
            f"read the check runs of {commit}",
        )
        runs = cast(list[dict[str, Any]], cast(dict[str, Any], found)["check_runs"])
        return [CheckRun(str(run["name"]), _outcome(run)) for run in runs]

    def git_state(self, checkout: Path) -> GitState:
        found = shutil.which("git")
        if found is None:
            raise HostError("git is not installed (install it with `xcode-select --install`)")
        git = [found, "-C", str(checkout)]
        env = {key: value for key, value in os.environ.items() if key not in GIT_LOCATION_VARS}
        quick = QUICK_COMMAND_TIMEOUT_SECONDS
        head = _run(
            [*git, "rev-parse", "--verify", "HEAD"],
            "read the checkout's HEAD",
            timeout=quick,
            env=env,
        ).strip()
        branch = _ref(
            [*git, "symbolic-ref", "--quiet", "--short", "HEAD"],
            "read the checkout's branch",
            env=env,
        )
        status = _run(
            [*git, "status", "--porcelain"], "read the checkout's status", timeout=quick, env=env
        )
        origin_main = _ref(
            [*git, "rev-parse", "--verify", "--quiet", ORIGIN_MAIN_REF],
            "read the checkout's origin/main",
            env=env,
        )
        return GitState(branch, clean=not status.strip(), head=head, origin_main=origin_main)

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
        doing = f"ask launchd about {label}"
        shown = _command([LAUNCHCTL, "print", f"{_domain()}/{label}"], doing)
        if shown.returncode == LAUNCHCTL_NO_SUCH_SERVICE:
            return JobState(loaded=False)
        if shown.returncode != 0:
            raise HostError(_failure(doing, shown))
        pid = PID_LINE.search(shown.stdout) if RUNNING_STATE.search(shown.stdout) else None
        return JobState(loaded=True, pid=int(pid.group(1)) if pid else None)

    def load(self, plist: Path) -> None:
        doing = f"load {plist}"
        done = _command([LAUNCHCTL, "bootstrap", _domain(), str(plist)], doing)
        if done.returncode in LAUNCHCTL_BUSY_CODES:
            raise JobBusy(_failure(doing, done))
        if done.returncode != 0:
            raise HostError(_failure(doing, done))

    def unload(self, label: str) -> None:
        _run([LAUNCHCTL, "bootout", f"{_domain()}/{label}"], f"boot out {label}")

    def activitywatch_running(self) -> bool:
        doing = "look for ActivityWatch's process"
        found = _command(
            [PGREP, "-x", "-U", str(os.getuid()), ACTIVITYWATCH_PROCESS],
            doing,
            timeout=QUICK_COMMAND_TIMEOUT_SECONDS,
        )
        if found.returncode not in (0, PGREP_NONE_FOUND):
            raise HostError(_failure(doing, found))
        return found.returncode == 0

    def open_activitywatch(self) -> None:
        _run(list(OPEN_ACTIVITYWATCH), "open ActivityWatch", timeout=QUICK_COMMAND_TIMEOUT_SECONDS)

    def notify(self, message: str) -> None:
        if os.environ.get(NOTIFY_ENV_VAR) == "0":
            return
        script = [arg for line in NOTIFY_SCRIPT for arg in ("-e", line)]
        _run(
            [OSASCRIPT, *script, NOTIFICATION_TITLE, message],
            "post a notification",
            timeout=QUICK_COMMAND_TIMEOUT_SECONDS,
        )


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


def _github(path: str, doing: str) -> object:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": COMMAND_NAME}
    token = os.environ.get(GITHUB_TOKEN_ENV_VAR)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(GITHUB_API + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=GITHUB_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise HostError(f"could not {doing} from GitHub: {_refusal(exc, bool(token))}") from exc
    except (OSError, ValueError) as exc:
        raise HostError(f"could not {doing} from GitHub: {exc}") from exc


def _refusal(exc: urllib.error.HTTPError, authenticated: bool) -> str:
    if exc.code not in RATE_LIMITED_STATUSES or exc.headers.get("X-RateLimit-Remaining") != "0":
        return f"GitHub answered {exc.code} {exc.reason}"
    reset = str(exc.headers.get("X-RateLimit-Reset", ""))
    at = datetime.fromtimestamp(int(reset)).strftime("%H:%M") if reset.isdigit() else "soon"
    if authenticated:
        return f"GitHub's rate limit for $GITHUB_TOKEN is used up; it resets at {at}"
    return (
        "GitHub's unauthenticated rate limit (60 requests an hour) is used up; it resets at"
        f" {at}, or set ${GITHUB_TOKEN_ENV_VAR} to raise it"
    )


def _command(
    command: list[str],
    doing: str,
    *,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HostError(f"could not {doing}: {exc}") from exc


def _failure(doing: str, done: subprocess.CompletedProcess[str]) -> str:
    detail = (done.stderr or done.stdout).strip().splitlines()
    return f"could not {doing}: {detail[-1] if detail else f'exit code {done.returncode}'}"


def _ref(command: list[str], doing: str, *, env: dict[str, str] | None = None) -> str | None:
    done = _command(command, doing, timeout=QUICK_COMMAND_TIMEOUT_SECONDS, env=env)
    if done.returncode == GIT_REF_MISSING:
        return None
    if done.returncode != 0:
        raise HostError(_failure(doing, done))
    return done.stdout.strip()


def _run(
    command: list[str],
    doing: str,
    *,
    timeout: float = COMMAND_TIMEOUT_SECONDS,
    env: dict[str, str] | None = None,
) -> str:
    done = _command(command, doing, timeout=timeout, env=env)
    if done.returncode != 0:
        raise HostError(_failure(doing, done))
    return done.stdout
