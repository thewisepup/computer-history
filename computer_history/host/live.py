from __future__ import annotations

import json
import os
import plistlib
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar, cast

from computer_history.host.contract import (
    COMMAND_NAME,
    OPEN_ACTIVITYWATCH,
    SPOOL_READS_FLAG,
    AgentNotUnregistered,
    BackendBuild,
    CheckOutcome,
    CheckRun,
    HostError,
    JobBusy,
    JobState,
    SpoolReads,
)

Answer = TypeVar("Answer")
REPO = "thewisepup/computer-history"
GITHUB_API = f"https://api.github.com/repos/{REPO}"
REPO_GIT_URL = f"https://github.com/{REPO}"
GITHUB_TOKEN_ENV_VAR = "GITHUB_TOKEN"
GITHUB_TIMEOUT_SECONDS = 15
CHECK_RUNS_PAGE = 100
RATE_LIMITED_STATUSES = frozenset({403, 429})
PYTHON_VERSION = "3.12"
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
XCRUN = "/usr/bin/xcrun"
SECURITY = "/usr/bin/security"
DITTO = "/usr/bin/ditto"
AGENT_SOURCE_FOLDER = "capture-agent"
AGENT_BUILD_SCRIPT = Path("scripts") / "build.sh"
AGENT_BUILT_APP = Path(".build") / "ComputerHistoryAgent.app"
SIGNING_IDENTITY = "Computer History Code Signing"
AGENT_BUILD_TIMEOUT_SECONDS = 1800
AGENT_REGISTER_ATTEMPTS = 3
AGENT_RUNNING_CHECKS = 6
AGENT_RUNNING_CHECK_SECONDS = 0.5
AGENT_REGISTER_RETRY_SECONDS = 1.0
NOTIFY_ENV_VAR = "COMPUTER_HISTORY_NOTIFY"
NOTIFICATION_TITLE = "Computer History"
NOTIFY_SCRIPT = (
    "on run argv",
    "display notification (item 2 of argv) with title (item 1 of argv)",
    "end run",
)


class LiveHost:
    """The host adapter for this Mac: launchctl in the login session, GitHub's API, uv, Swift and
    codesign through the agent's build script, pgrep, open and osascript (off when
    $COMPUTER_HISTORY_NOTIFY is 0)."""

    def __init__(
        self,
        *,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sleep = sleep
        self._now = now

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

    def build(self, commit: str, venv: Path) -> BackendBuild:
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
        reads = _spool_reads(
            _run([str(venv / "bin" / COMMAND_NAME), SPOOL_READS_FLAG], "run the built command")
        )
        packages = _run([uv, "pip", "freeze", "--python", python], "list the installed packages")
        return BackendBuild(packages, reads)

    def agent_tree(self, commit: str) -> str:
        doing = f"read the capture agent's source tree at {commit}"
        listing = _github(f"/contents?ref={commit}", doing)
        if isinstance(listing, list):
            for entry in cast(list[dict[str, Any]], listing):
                if entry.get("name") == AGENT_SOURCE_FOLDER and entry.get("type") == "dir":
                    return str(entry["sha"])
        raise HostError(f"could not {doing}: GitHub lists no {AGENT_SOURCE_FOLDER} folder there")

    def check_agent_toolchain(self) -> None:
        missing: list[str] = []
        found = _command(
            [XCRUN, "--find", "swift"], "look for Swift", timeout=QUICK_COMMAND_TIMEOUT_SECONDS
        )
        if found.returncode != 0:
            missing.append("Swift is not installed (run `xcode-select --install`)")
        identities = _run(
            [SECURITY, "find-identity", "-p", "codesigning"],
            "list the signing identities",
            timeout=QUICK_COMMAND_TIMEOUT_SECONDS,
        )
        if f'"{SIGNING_IDENTITY}"' not in identities:
            missing.append(
                f'the signing identity "{SIGNING_IDENTITY}" is not in your keychain (create a'
                " code-signing certificate of that name in Keychain Access)"
            )
        if missing:
            raise HostError("; ".join(missing))

    def build_agent(self, commit: str, app: Path) -> None:
        with tempfile.TemporaryDirectory(prefix=f"{COMMAND_NAME}-agent-") as scratch:
            source = _export(commit, Path(scratch)) / AGENT_SOURCE_FOLDER
            _run(
                ["/bin/sh", str(source / AGENT_BUILD_SCRIPT)],
                f"build and sign the capture agent at {commit}",
                timeout=AGENT_BUILD_TIMEOUT_SECONDS,
                env=os.environ | {"CODESIGN_IDENTITY": SIGNING_IDENTITY},
            )
            app.parent.mkdir(parents=True, exist_ok=True)
            _run([DITTO, str(source / AGENT_BUILT_APP), str(app)], "copy the built agent")

    def install_agent(self, app: Path, fixed: Path) -> datetime:
        executable = Path("Contents") / "MacOS" / _bundle_executable(app)
        label = _bundle_label(app)
        old = _existing_executable(fixed)
        if old is not None:
            try:
                _run([str(old), "uninstall"], "unregister the installed capture agent")
            except HostError as exc:
                raise AgentNotUnregistered(str(exc)) from exc
        if fixed.exists():
            shutil.rmtree(fixed)
        fixed.parent.mkdir(parents=True, exist_ok=True)
        _run([DITTO, str(app), str(fixed)], f"copy the capture agent to {fixed}")
        agent = str(fixed / executable)
        registered_at = self._now()
        _run([agent, "install"], "register the capture agent")
        for attempt in range(AGENT_REGISTER_ATTEMPTS):
            if self._agent_running(label):
                return registered_at
            if attempt == AGENT_REGISTER_ATTEMPTS - 1:
                break
            _command([LAUNCHCTL, "kickstart", f"{_domain()}/{label}"], f"kickstart {label}")
            self._sleep(AGENT_REGISTER_RETRY_SECONDS)
            _run([agent, "uninstall"], "unregister the capture agent")
            _run([agent, "install"], "register the capture agent")
        raise HostError(
            "the capture agent is registered but did not start (check: launchctl print"
            f" {_domain()}/{label})"
        )

    def _agent_running(self, label: str) -> bool:
        for check in range(AGENT_RUNNING_CHECKS):
            if self.job(label).pid is not None:
                return True
            if check < AGENT_RUNNING_CHECKS - 1:
                self._sleep(AGENT_RUNNING_CHECK_SECONDS)
        return False

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


def _spool_reads(answer: str) -> SpoolReads:
    try:
        return SpoolReads.from_json(answer)
    except ValueError as exc:
        raise HostError(
            f"could not ask the built command what it reads: {exc} in {answer.strip()[:200]!r}"
        ) from exc


def _export(commit: str, scratch: Path) -> Path:
    """Download and unpack a commit's files from GitHub, returning the folder that holds them."""
    tarball = scratch / "source.tar.gz"
    _github_download(f"/tarball/{commit}", tarball, f"download commit {commit}")
    unpacked = scratch / "source"
    try:
        with tarfile.open(tarball) as archive:
            archive.extractall(unpacked, filter="data")
    except (OSError, tarfile.TarError) as exc:
        raise HostError(f"could not unpack commit {commit}: {exc}") from exc
    tops = list(unpacked.iterdir())
    if len(tops) != 1:
        raise HostError(f"could not unpack commit {commit}: {len(tops)} top folders")
    return tops[0]


def _bundle_executable(app: Path) -> str:
    try:
        info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
        return str(info["CFBundleExecutable"])
    except (OSError, plistlib.InvalidFileException, KeyError) as exc:
        raise HostError(f"could not read the executable name of {app}: {exc}") from exc


def _bundle_label(app: Path) -> str:
    plists = sorted((app / "Contents" / "Library" / "LaunchAgents").glob("*.plist"))
    try:
        return str(plistlib.loads(plists[0].read_bytes())["Label"])
    except (IndexError, OSError, plistlib.InvalidFileException, KeyError) as exc:
        raise HostError(f"could not read the launch agent label of {app}: {exc}") from exc


def _existing_executable(fixed: Path) -> Path | None:
    try:
        found = fixed / "Contents" / "MacOS" / _bundle_executable(fixed)
    except HostError:
        return None
    return found if found.is_file() else None


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
    return _from_github(path, doing, json.load)


def _github_download(path: str, target: Path, doing: str) -> None:
    def save(response: Any) -> None:
        with target.open("wb") as saved:
            shutil.copyfileobj(response, saved)

    _from_github(path, doing, save)


def _from_github(path: str, doing: str, read: Callable[[Any], Answer]) -> Answer:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": COMMAND_NAME}
    token = os.environ.get(GITHUB_TOKEN_ENV_VAR)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(GITHUB_API + path, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=GITHUB_TIMEOUT_SECONDS) as response:
            return read(response)
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
