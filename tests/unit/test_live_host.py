"""How the live host reads GitHub and launchctl, both answering with canned replies."""

from __future__ import annotations

import io
import json
import subprocess
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from computer_history.host import (
    OPEN_ACTIVITYWATCH,
    CheckOutcome,
    CheckRun,
    GitState,
    HostError,
    JobBusy,
    JobState,
    LiveHost,
    live,
)
from computer_history.stable import BACKEND

LAUNCHCTL_RUNNING = f"""gui/501/{BACKEND.label} = {{
\tactive count = 1
\tpath = /Users/someone/Library/LaunchAgents/{BACKEND.label}.plist
\ttype = LaunchAgent
\tstate = running

\tprogram = /Users/someone/.local/bin/computer-history
\tpid = 4242
\tlast exit code = (never exited)
}}
"""
LAUNCHCTL_WAITING = LAUNCHCTL_RUNNING.replace("state = running", "state = not running").replace(
    "\tpid = 4242\n", ""
)
UV = "/opt/homebrew/bin/uv"
GIT = "/usr/bin/git"
HEAD = "c" * 40
ORIGIN_MAIN = "d" * 40


@pytest.fixture(autouse=True)
def no_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(live.GITHUB_TOKEN_ENV_VAR, raising=False)


@pytest.fixture(autouse=True)
def notifications_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(live.NOTIFY_ENV_VAR, raising=False)


def github_answers(monkeypatch: pytest.MonkeyPatch, answer: object) -> list[urllib.request.Request]:
    asked: list[urllib.request.Request] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> io.BytesIO:
        asked.append(request)
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(json.dumps(answer).encode())

    monkeypatch.setattr(live.urllib.request, "urlopen", urlopen)
    return asked


def rate_limited(status: int, remaining: str) -> urllib.error.HTTPError:
    headers = Message()
    headers["X-RateLimit-Remaining"] = remaining
    headers["X-RateLimit-Reset"] = "1795000000"
    return urllib.error.HTTPError(live.GITHUB_API, status, "rate limit exceeded", headers, None)


def commands_answer(
    monkeypatch: pytest.MonkeyPatch, returncode: int = 0, stdout: str = "", stderr: str = ""
) -> list[list[str]]:
    ran: list[list[str]] = []

    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        ran.append(command)
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    monkeypatch.setattr(live.subprocess, "run", run)
    return ran


def test_check_runs_read_running_failed_and_cancelled_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    runs = [
        {"name": "unit", "status": "completed", "conclusion": "success"},
        {"name": "data", "status": "in_progress", "conclusion": None},
        {"name": "poc", "status": "queued", "conclusion": None},
        {"name": "lint", "status": "completed", "conclusion": "failure"},
        {"name": "secrets", "status": "completed", "conclusion": "cancelled"},
        {"name": "perf", "status": "completed", "conclusion": "timed_out"},
        {"name": "typecheck", "status": "completed", "conclusion": "skipped"},
    ]
    asked = github_answers(monkeypatch, {"total_count": len(runs), "check_runs": runs})

    found = LiveHost().check_runs("abc123")

    assert found == [
        CheckRun("unit", CheckOutcome.SUCCESS),
        CheckRun("data", CheckOutcome.RUNNING),
        CheckRun("poc", CheckOutcome.RUNNING),
        CheckRun("lint", CheckOutcome.FAILURE),
        CheckRun("secrets", CheckOutcome.CANCELLED),
        CheckRun("perf", CheckOutcome.FAILURE),
        CheckRun("typecheck", CheckOutcome.FAILURE),
    ]
    assert [request.full_url for request in asked] == [
        f"{live.GITHUB_API}/commits/abc123/check-runs?per_page={live.CHECK_RUNS_PAGE}"
    ]


def test_main_commits_are_read_newest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = github_answers(monkeypatch, [{"sha": "c" * 40}, {"sha": "b" * 40}])

    assert LiveHost().main_commits(2) == ["c" * 40, "b" * 40]
    assert [request.full_url for request in asked] == [
        f"{live.GITHUB_API}/commits?sha=main&per_page=2"
    ]
    assert asked[0].get_header("Authorization") is None


def test_a_token_in_the_environment_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(live.GITHUB_TOKEN_ENV_VAR, "ghp_example")
    asked = github_answers(monkeypatch, [])

    LiveHost().main_commits(2)

    assert asked[0].get_header("Authorization") == "Bearer ghp_example"


def test_github_out_of_reach_names_the_call_that_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    github_answers(monkeypatch, OSError("nodename nor servname provided"))

    with pytest.raises(
        HostError, match="could not read the check runs of abc123 from GitHub: node"
    ):
        LiveHost().check_runs("abc123")


@pytest.mark.parametrize("status", [403, 429])
def test_the_unauthenticated_rate_limit_is_named_with_when_it_resets(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    github_answers(monkeypatch, rate_limited(status, "0"))

    with pytest.raises(HostError) as raised:
        LiveHost().main_commits(20)

    message = str(raised.value)
    assert message.startswith("could not list main's newest commits from GitHub: ")
    assert "unauthenticated rate limit (60 requests an hour) is used up; it resets at " in message
    assert f"${live.GITHUB_TOKEN_ENV_VAR}" in message


def test_another_refusal_says_what_github_answered(monkeypatch: pytest.MonkeyPatch) -> None:
    github_answers(monkeypatch, rate_limited(403, "41"))

    with pytest.raises(HostError, match="GitHub answered 403 rate limit exceeded$"):
        LiveHost().main_commits(20)


@pytest.mark.parametrize(
    ("returncode", "stdout", "state"),
    [
        (0, LAUNCHCTL_RUNNING, JobState(loaded=True, pid=4242)),
        (0, LAUNCHCTL_WAITING, JobState(loaded=True)),
        (live.LAUNCHCTL_NO_SUCH_SERVICE, "Could not find service", JobState(loaded=False)),
    ],
    ids=["running", "loaded, not running", "not loaded"],
)
def test_job_reads_launchctl_print(
    monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str, state: JobState
) -> None:
    commands_answer(monkeypatch, returncode, stdout)

    assert LiveHost().job(BACKEND.label) == state


def test_a_launchctl_print_that_fails_otherwise_is_a_host_error_not_an_unloaded_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands_answer(monkeypatch, 5, stderr="Could not connect to the bootstrap server")

    with pytest.raises(HostError, match="bootstrap server"):
        LiveHost().job(BACKEND.label)


@pytest.mark.parametrize("returncode", sorted(live.LAUNCHCTL_BUSY_CODES))
def test_a_busy_bootstrap_is_a_job_busy_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, returncode: int
) -> None:
    commands_answer(monkeypatch, returncode, stderr="Bootstrap failed: 5: Input/output error")

    with pytest.raises(JobBusy, match="Input/output error"):
        LiveHost().load(tmp_path / f"{BACKEND.label}.plist")


def test_another_bootstrap_failure_is_a_plain_host_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands_answer(monkeypatch, 1, stderr="Bootstrap failed: 1: Operation not permitted")

    with pytest.raises(HostError, match="not permitted") as raised:
        LiveHost().load(tmp_path / f"{BACKEND.label}.plist")
    assert not isinstance(raised.value, JobBusy)


def git_answers(
    monkeypatch: pytest.MonkeyPatch, answers: dict[str, tuple[int, str, str]]
) -> list[list[str]]:
    """git answering each subcommand (the words after -C and the folder) as given."""
    ran: list[list[str]] = []
    monkeypatch.setattr(live.shutil, "which", lambda name: GIT if name == "git" else None)

    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        ran.append(command)
        returncode, stdout, stderr = answers[" ".join(command[3:])]
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    monkeypatch.setattr(live.subprocess, "run", run)
    return ran


GIT_ON_MAIN = {
    "rev-parse --verify HEAD": (0, f"{HEAD}\n", ""),
    "symbolic-ref --quiet --short HEAD": (0, "main\n", ""),
    "status --porcelain": (0, "", ""),
    "rev-parse --verify --quiet refs/remotes/origin/main": (0, f"{ORIGIN_MAIN}\n", ""),
}


def test_git_state_reads_branch_tree_head_and_origin_main_without_fetching(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ran = git_answers(monkeypatch, GIT_ON_MAIN)

    state = LiveHost().git_state(tmp_path)

    assert state == GitState(branch="main", clean=True, head=HEAD, origin_main=ORIGIN_MAIN)
    assert all(command[:3] == [GIT, "-C", str(tmp_path)] for command in ran)
    assert sorted(" ".join(command[3:]) for command in ran) == sorted(GIT_ON_MAIN)


def test_git_state_reads_a_detached_head_a_dirty_tree_and_no_origin_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    git_answers(
        monkeypatch,
        GIT_ON_MAIN
        | {
            "symbolic-ref --quiet --short HEAD": (1, "", ""),
            "status --porcelain": (0, "?? notes.txt\n", ""),
            "rev-parse --verify --quiet refs/remotes/origin/main": (1, "", ""),
        },
    )

    state = LiveHost().git_state(tmp_path)

    assert state == GitState(branch=None, clean=False, head=HEAD, origin_main=None)


def test_git_state_outside_a_checkout_is_a_host_error_with_gits_words(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    refused = "fatal: not a git repository (or any of the parent directories): .git"
    git_answers(
        monkeypatch,
        {command: (128, "", refused) for command in GIT_ON_MAIN},
    )

    with pytest.raises(HostError, match=r"could not read the checkout's HEAD: fatal: not a git"):
        LiveHost().git_state(tmp_path)


def test_git_state_without_git_is_a_host_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(live.shutil, "which", lambda _: None)

    with pytest.raises(HostError, match="git is not installed"):
        LiveHost().git_state(tmp_path)


def test_the_build_creates_installs_smokes_and_freezes_with_uv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(live.shutil, "which", lambda _: UV)
    ran = commands_answer(monkeypatch, stdout="computer-history @ git+...\n")
    venv = tmp_path / "venv"
    python = str(venv / "bin" / "python")

    packages = LiveHost().build("abc123", venv)

    assert ran == [
        [
            UV,
            "venv",
            "--python",
            live.PYTHON_VERSION,
            "--python-preference",
            "only-managed",
            str(venv),
        ],
        [
            UV,
            "pip",
            "install",
            "--python",
            python,
            f"computer-history @ git+{live.REPO_GIT_URL}@abc123",
        ],
        [str(venv / "bin" / "computer-history"), "--help"],
        [UV, "pip", "freeze", "--python", python],
    ]
    assert packages == "computer-history @ git+...\n"


def test_a_failed_build_step_names_the_step(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(live.shutil, "which", lambda _: UV)
    commands_answer(monkeypatch, 2, stderr="error: Failed to download Python 3.12")

    with pytest.raises(
        HostError, match="create the virtual environment: error: Failed to download"
    ):
        LiveHost().build("abc123", tmp_path / "venv")


def test_build_without_uv_is_a_host_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(live.shutil, "which", lambda _: None)

    with pytest.raises(HostError, match="uv is not installed"):
        LiveHost().build("abc123", tmp_path / "venv")

    assert not (tmp_path / "venv").exists()


@pytest.mark.parametrize(("returncode", "running"), [(0, True), (live.PGREP_NONE_FOUND, False)])
def test_activitywatch_running_asks_pgrep_for_this_users_app(
    monkeypatch: pytest.MonkeyPatch, returncode: int, running: bool
) -> None:
    ran = commands_answer(monkeypatch, returncode)

    assert LiveHost().activitywatch_running() is running
    ((command),) = ran
    assert command[0] == live.PGREP and command[-1] == live.ACTIVITYWATCH_PROCESS


def test_a_failed_pgrep_is_a_host_error(monkeypatch: pytest.MonkeyPatch) -> None:
    commands_answer(monkeypatch, 3, stderr="pgrep: internal error")

    with pytest.raises(HostError, match="ActivityWatch's process: pgrep: internal error"):
        LiveHost().activitywatch_running()


def test_opening_activitywatch_runs_the_login_agents_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran = commands_answer(monkeypatch)

    LiveHost().open_activitywatch()

    assert ran == [list(OPEN_ACTIVITYWATCH)]


def test_a_notification_passes_its_text_as_arguments_never_as_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran = commands_answer(monkeypatch)
    message = 'He said "quit" & tell application "Finder" to quit'

    LiveHost().notify(message)

    ((command),) = ran
    assert command[0] == live.OSASCRIPT
    assert command[-2:] == [live.NOTIFICATION_TITLE, message]
    assert all(message not in arg for arg in command[:-1])


def test_notifications_turned_off_post_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    ran = commands_answer(monkeypatch)
    monkeypatch.setenv(live.NOTIFY_ENV_VAR, "0")

    LiveHost().notify("hello")

    assert ran == []


def test_a_notification_osascript_refuses_is_a_host_error(monkeypatch: pytest.MonkeyPatch) -> None:
    commands_answer(monkeypatch, 1, stderr="execution error: Not authorized (-1743)")

    with pytest.raises(HostError, match="post a notification: execution error"):
        LiveHost().notify("hello")


@pytest.mark.parametrize(
    "call",
    [
        lambda host: host.activitywatch_running(),
        lambda host: host.open_activitywatch(),
        lambda host: host.notify("hello"),
    ],
    ids=["pgrep", "open", "osascript"],
)
def test_the_quick_commands_time_out_well_before_a_build(
    monkeypatch: pytest.MonkeyPatch, call: Any
) -> None:
    timeouts: list[float] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        timeouts.append(kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(live.subprocess, "run", run)

    call(LiveHost())

    assert timeouts == [live.QUICK_COMMAND_TIMEOUT_SECONDS]
    assert live.QUICK_COMMAND_TIMEOUT_SECONDS < live.COMMAND_TIMEOUT_SECONDS


def test_a_hung_osascript_is_a_host_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def hang(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(live.subprocess, "run", hang)

    with pytest.raises(HostError, match="could not post a notification"):
        LiveHost().notify("hello")
