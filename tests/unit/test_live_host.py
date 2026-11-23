"""How the live host reads GitHub and launchctl, both answering with canned replies."""

from __future__ import annotations

import io
import json
import os
import plistlib
import subprocess
import tarfile
import urllib.error
import urllib.request
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from computer_history.host import (
    OPEN_ACTIVITYWATCH,
    AgentNotUnregistered,
    BackendBuild,
    CheckOutcome,
    CheckRun,
    GitState,
    HostError,
    JobBusy,
    JobState,
    LiveHost,
    SpoolReads,
    live,
)
from computer_history.stable import BACKEND, CAPTURE_AGENT_LABEL

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


def commands_answer_each(
    monkeypatch: pytest.MonkeyPatch, answers: dict[str, tuple[int, str, str]]
) -> list[list[str]]:
    """Commands answered by their program: exit code, stdout and stderr; any other succeeds."""
    ran: list[list[str]] = []

    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        ran.append(command)
        code, stdout, stderr = answers.get(command[0], (0, "", ""))
        return subprocess.CompletedProcess(command, code, stdout, stderr)

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


HOSTILE_HASHES = ["..", "../../.", "c" * 39, "C" * 40, "c" * 40 + "/..", None]


@pytest.mark.parametrize("sha", HOSTILE_HASHES)
def test_main_commits_github_answers_that_are_not_commit_hashes_are_refused(
    monkeypatch: pytest.MonkeyPatch, sha: object
) -> None:
    github_answers(monkeypatch, [{"sha": "c" * 40}, {"sha": sha}])

    with pytest.raises(HostError, match="could not list main's newest commits from GitHub: it"):
        LiveHost().main_commits(2)


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


def test_git_state_ignores_git_location_variables_and_answers_quickly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(live.shutil, "which", lambda name: GIT if name == "git" else None)
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        monkeypatch.setenv(name, str(tmp_path / "elsewhere"))
    seen: list[dict[str, Any]] = []

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen.append(kwargs)
        returncode, stdout, stderr = GIT_ON_MAIN[" ".join(command[3:])]
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)

    monkeypatch.setattr(live.subprocess, "run", run)

    LiveHost().git_state(tmp_path)

    assert all(not {"GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"} & set(kw["env"]) for kw in seen)
    assert all(kw["timeout"] == live.QUICK_COMMAND_TIMEOUT_SECONDS for kw in seen)


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


def test_the_build_creates_installs_asks_what_it_reads_and_freezes_with_uv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(live.shutil, "which", lambda _: UV)
    venv = tmp_path / "venv"
    python = str(venv / "bin" / "python")
    command = str(venv / "bin" / "computer-history")
    ran = commands_answer_each(
        monkeypatch,
        {
            command: (0, '{"spool_version": 3, "kinds": ["capture", "paused"]}\n', ""),
            UV: (0, "computer-history @ git+...\n", ""),
        },
    )

    built = LiveHost().build("abc123", venv)

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
        [command, "--spool-reads"],
        [UV, "pip", "freeze", "--python", python],
    ]
    assert built == BackendBuild(
        "computer-history @ git+...\n", SpoolReads(3, ("capture", "paused"))
    )


@pytest.mark.parametrize(
    "answer",
    [
        "usage: computer-history [-h]\n",
        "[" * 100_000,
        '{"spool_version": "1", "kinds": []}\n',
        '{"kinds": []}\n',
    ],
    ids=["not json", "nested past the parser limit", "version not a number", "no version"],
)
def test_a_built_command_that_cannot_say_what_it_reads_fails_the_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, answer: str
) -> None:
    monkeypatch.setattr(live.shutil, "which", lambda _: UV)
    venv = tmp_path / "venv"
    commands_answer_each(monkeypatch, {str(venv / "bin" / "computer-history"): (0, answer, "")})

    with pytest.raises(HostError, match="could not ask the built command what it reads: "):
        LiveHost().build("abc123", venv)


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


def test_the_agent_tree_is_the_hash_github_lists_for_its_source_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listing = [
        {"name": "README.md", "type": "file", "sha": "1" * 40},
        {"name": live.AGENT_SOURCE_FOLDER, "type": "dir", "sha": "2" * 40},
    ]
    asked = github_answers(monkeypatch, listing)

    assert LiveHost().agent_tree("abc123") == "2" * 40
    assert [request.full_url for request in asked] == [f"{live.GITHUB_API}/contents?ref=abc123"]


@pytest.mark.parametrize(
    "answer",
    [[{"name": "README.md", "type": "file", "sha": "1" * 40}], {"message": "Not Found"}],
    ids=["no agent folder", "not a listing"],
)
def test_an_agent_tree_github_does_not_list_is_a_host_error(
    monkeypatch: pytest.MonkeyPatch, answer: object
) -> None:
    github_answers(monkeypatch, answer)

    with pytest.raises(HostError, match="could not read the capture agent's source tree at abc"):
        LiveHost().agent_tree("abc123")


@pytest.mark.parametrize("sha", HOSTILE_HASHES)
def test_an_agent_tree_that_is_not_a_hash_is_a_host_error(
    monkeypatch: pytest.MonkeyPatch, sha: object
) -> None:
    github_answers(monkeypatch, [{"name": live.AGENT_SOURCE_FOLDER, "type": "dir", "sha": sha}])

    with pytest.raises(HostError, match="source tree at abc123 from GitHub: it answered"):
        LiveHost().agent_tree("abc123")


def test_an_agent_tree_out_of_reach_is_a_host_error(monkeypatch: pytest.MonkeyPatch) -> None:
    github_answers(monkeypatch, OSError("nodename nor servname provided"))

    with pytest.raises(HostError, match="source tree at abc123 from GitHub: nodename"):
        LiveHost().agent_tree("abc123")


IDENTITIES = (
    '  1) 0123456789ABCDEF0123456789ABCDEF01234567 "Computer History Code Signing"\n'
    "     1 valid identities found\n"
)
UNTRUSTED_IDENTITY = (
    "Policy: Code Signing\n"
    "  Matching identities\n"
    '  1) 0123456789ABCDEF0123456789ABCDEF01234567 "Computer History Code Signing"'
    " (CSSMERR_TP_NOT_TRUSTED)\n"
    "     1 identities found\n\n"
    "  Valid identities only\n"
    "     0 valid identities found\n"
)


def test_the_agent_toolchain_asks_xcrun_for_swift_and_security_for_any_signing_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ran = commands_answer_each(monkeypatch, {live.SECURITY: (0, IDENTITIES, "")})

    LiveHost().check_agent_toolchain()

    assert ran == [
        [live.XCRUN, "--find", "swift"],
        [live.SECURITY, "find-identity", "-p", "codesigning"],
    ]


def test_an_untrusted_self_signed_identity_is_enough_for_the_agent_toolchain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands_answer_each(monkeypatch, {live.SECURITY: (0, UNTRUSTED_IDENTITY, "")})

    LiveHost().check_agent_toolchain()


@pytest.mark.parametrize(
    ("answers", "missing"),
    [
        (
            {
                live.XCRUN: (1, "", "xcrun: error: invalid active developer path"),
                live.SECURITY: (0, IDENTITIES, ""),
            },
            ["Swift is not installed (run `xcode-select --install`)"],
        ),
        (
            {live.SECURITY: (0, "     0 valid identities found\n", "")},
            [
                'the signing identity "Computer History Code Signing" is not in your keychain'
                " (create a code-signing certificate of that name in Keychain Access)"
            ],
        ),
        (
            {
                live.XCRUN: (1, "", "xcrun: error: invalid active developer path"),
                live.SECURITY: (0, "     0 valid identities found\n", ""),
            },
            [
                "Swift is not installed (run `xcode-select --install`)",
                'the signing identity "Computer History Code Signing" is not in your keychain'
                " (create a code-signing certificate of that name in Keychain Access)",
            ],
        ),
    ],
    ids=["no swift", "no identity", "neither"],
)
def test_a_missing_agent_toolchain_names_everything_missing_and_how_to_get_it(
    monkeypatch: pytest.MonkeyPatch, answers: dict[str, tuple[int, str, str]], missing: list[str]
) -> None:
    commands_answer_each(monkeypatch, answers)

    with pytest.raises(HostError) as raised:
        LiveHost().check_agent_toolchain()

    assert str(raised.value) == "; ".join(missing)


def source_tarball(commit: str) -> bytes:
    """A GitHub tarball of a commit: one top folder holding the agent's build script."""
    packed = io.BytesIO()
    with tarfile.open(fileobj=packed, mode="w:gz") as archive:
        script = b"#!/bin/sh\necho built\n"
        entry = tarfile.TarInfo(
            f"thewisepup-computer-history-{commit[:7]}/capture-agent/scripts/build.sh"
        )
        entry.size, entry.mode = len(script), 0o755
        archive.addfile(entry, io.BytesIO(script))
    return packed.getvalue()


def tarball_answers(monkeypatch: pytest.MonkeyPatch, answer: bytes) -> list[str]:
    asked: list[str] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> io.BytesIO:
        asked.append(request.full_url)
        return io.BytesIO(answer)

    monkeypatch.setattr(live.urllib.request, "urlopen", urlopen)
    return asked


def test_the_agent_is_built_by_its_own_commits_script_from_a_fresh_export(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    asked = tarball_answers(monkeypatch, source_tarball("abc1234"))
    seen: list[tuple[list[str], dict[str, str]]] = []

    def run(command: list[str], **options: Any) -> subprocess.CompletedProcess[str]:
        seen.append((command, dict(options.get("env") or {})))
        if command[0] == "/bin/sh":
            assert Path(command[1]).read_bytes() == b"#!/bin/sh\necho built\n"
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(live.subprocess, "run", run)
    app = tmp_path / "version" / "ComputerHistoryAgent.app"

    LiveHost().build_agent("abc1234", app)

    assert asked == [f"{live.GITHUB_API}/tarball/abc1234"]
    (build, build_env), (copy, _) = seen
    export = Path(build[1]).parents[2]
    assert build == ["/bin/sh", str(export / "capture-agent" / "scripts" / "build.sh")]
    assert build_env["CODESIGN_IDENTITY"] == live.SIGNING_IDENTITY
    assert copy == [live.DITTO, str(export / "capture-agent" / ".build" / app.name), str(app)]
    assert not export.exists()


def test_a_failed_agent_build_is_a_host_error_with_the_builds_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    tarball_answers(monkeypatch, source_tarball("abc1234"))
    commands_answer_each(
        monkeypatch, {"/bin/sh": (1, "error: no such module 'CaptureAgent'\n", "")}
    )

    with pytest.raises(
        HostError,
        match="could not build and sign the capture agent at abc1234: error: no such module",
    ):
        LiveHost().build_agent("abc1234", tmp_path / "ComputerHistoryAgent.app")


def agent_app(folder: Path, executable: str = "ComputerHistoryAgent") -> Path:
    """An agent bundle with its Info.plist and LaunchAgent plist, as the build script lays out."""
    app = folder / "ComputerHistoryAgent.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / executable).write_text("#!/bin/sh\n")
    (app / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps({"CFBundleExecutable": executable})
    )
    agents = app / "Contents" / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    (agents / f"{CAPTURE_AGENT_LABEL}.plist").write_bytes(
        plistlib.dumps({"Label": CAPTURE_AGENT_LABEL})
    )
    return app


def launchd_runs_after(
    monkeypatch: pytest.MonkeyPatch, prints: int, register: tuple[int, str] = (0, "")
) -> list[list[str]]:
    """Commands answered as launchd would: the agent shows running from the given print on."""
    ran: list[list[str]] = []

    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        ran.append(command)
        if command[:2] == [live.LAUNCHCTL, "print"]:
            shown = sum(1 for c in ran if c[:2] == [live.LAUNCHCTL, "print"])
            out = LAUNCHCTL_RUNNING if shown >= prints else LAUNCHCTL_WAITING
            return subprocess.CompletedProcess(command, 0, out, "")
        if command[-1] == "install":
            return subprocess.CompletedProcess(command, register[0], "", register[1])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(live.subprocess, "run", run)
    return ran


def test_installing_the_agent_unregisters_the_old_app_replaces_it_and_registers_the_new(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = agent_app(tmp_path / "version")
    fixed = agent_app(tmp_path / "Applications", executable="OldAgent")
    ran = launchd_runs_after(monkeypatch, prints=1)
    registered = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)

    at = LiveHost(sleep=lambda _: None, now=lambda: registered).install_agent(app, fixed)

    assert at == registered
    job = f"gui/{os.getuid()}/{CAPTURE_AGENT_LABEL}"
    assert ran == [
        [str(fixed / "Contents" / "MacOS" / "OldAgent"), "uninstall"],
        [live.DITTO, str(app), str(fixed)],
        [str(fixed / "Contents" / "MacOS" / "ComputerHistoryAgent"), "install"],
        [live.LAUNCHCTL, "print", job],
    ]
    assert not fixed.exists()


def test_an_old_agent_that_cannot_be_unregistered_is_left_in_place(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = agent_app(tmp_path / "version")
    fixed = agent_app(tmp_path / "Applications", executable="OldAgent")
    ran = commands_answer_each(
        monkeypatch,
        {str(fixed / "Contents" / "MacOS" / "OldAgent"): (1, "", "Operation not permitted")},
    )

    with pytest.raises(
        AgentNotUnregistered, match="unregister the installed capture agent: Operation"
    ):
        LiveHost(sleep=lambda _: None).install_agent(app, fixed)

    assert ran == [[str(fixed / "Contents" / "MacOS" / "OldAgent"), "uninstall"]]
    assert (fixed / "Contents" / "MacOS" / "OldAgent").is_file()


def test_an_agent_that_does_not_start_is_kickstarted_and_registered_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = agent_app(tmp_path / "version")
    fixed = tmp_path / "Applications" / app.name
    ran = launchd_runs_after(monkeypatch, prints=live.AGENT_RUNNING_CHECKS + 1)

    LiveHost(sleep=lambda _: None).install_agent(app, fixed)

    job = f"gui/{os.getuid()}/{CAPTURE_AGENT_LABEL}"
    executable = str(fixed / "Contents" / "MacOS" / "ComputerHistoryAgent")
    retry = ran.index([live.LAUNCHCTL, "kickstart", job])
    assert ran[retry : retry + 3] == [
        [live.LAUNCHCTL, "kickstart", job],
        [executable, "uninstall"],
        [executable, "install"],
    ]
    assert ran[-1] == [live.LAUNCHCTL, "print", job]
    assert ran[0] == [live.DITTO, str(app), str(fixed)]


def test_an_agent_that_never_starts_is_a_host_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = agent_app(tmp_path / "version")
    launchd_runs_after(monkeypatch, prints=10_000)

    with pytest.raises(HostError, match="the capture agent is registered but did not start"):
        LiveHost(sleep=lambda _: None).install_agent(app, tmp_path / "Applications" / app.name)


def test_an_agent_that_cannot_register_is_a_host_error_with_its_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = agent_app(tmp_path / "version")
    launchd_runs_after(monkeypatch, prints=1, register=(1, "Operation not permitted"))

    with pytest.raises(HostError, match="could not register the capture agent: Operation not"):
        LiveHost(sleep=lambda _: None).install_agent(app, tmp_path / "Applications" / app.name)
