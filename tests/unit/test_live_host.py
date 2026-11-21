"""How the live host reads GitHub and launchctl, both answering with canned replies."""

from __future__ import annotations

import io
import json
import subprocess
import urllib.request
from typing import Any

import pytest

from computer_history.host import CheckOutcome, CheckRun, HostError, JobState, LiveHost, live

LAUNCHCTL_RUNNING = """gui/501/io.github.thewisepup.computer-history.ingest = {
\tactive count = 1
\tpath = /Users/someone/Library/LaunchAgents/io.github.thewisepup.computer-history.ingest.plist
\ttype = LaunchAgent
\tstate = running

\tprogram = /Users/someone/.local/bin/computer-history
\tpid = 4242
\tlast exit code = (never exited)
}
"""
LAUNCHCTL_WAITING = LAUNCHCTL_RUNNING.replace("state = running", "state = not running").replace(
    "\tpid = 4242\n", ""
)


def github_answers(monkeypatch: pytest.MonkeyPatch, answer: object) -> list[str]:
    asked: list[str] = []

    def urlopen(request: urllib.request.Request, timeout: float) -> io.BytesIO:
        asked.append(request.full_url)
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(json.dumps(answer).encode())

    monkeypatch.setattr(live.urllib.request, "urlopen", urlopen)
    return asked


def launchctl_answers(monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str) -> None:
    def run(command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, returncode, stdout, "")

    monkeypatch.setattr(live.subprocess, "run", run)


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
    assert asked == [f"{live.GITHUB_API}/commits/abc123/check-runs?per_page=100"]


def test_main_commits_are_read_newest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    asked = github_answers(monkeypatch, [{"sha": "c" * 40}, {"sha": "b" * 40}])

    assert LiveHost().main_commits(2) == ["c" * 40, "b" * 40]
    assert asked == [f"{live.GITHUB_API}/commits?sha=main&per_page=2"]


def test_github_out_of_reach_is_a_host_error(monkeypatch: pytest.MonkeyPatch) -> None:
    github_answers(monkeypatch, OSError("nodename nor servname provided"))

    with pytest.raises(HostError, match="could not read .* from GitHub: nodename"):
        LiveHost().main_commits(20)


@pytest.mark.parametrize(
    ("returncode", "stdout", "state"),
    [
        (0, LAUNCHCTL_RUNNING, JobState(loaded=True, pid=4242)),
        (0, LAUNCHCTL_WAITING, JobState(loaded=True)),
        (113, "Could not find service", JobState(loaded=False)),
    ],
    ids=["running", "loaded, not running", "not loaded"],
)
def test_job_reads_launchctl_print(
    monkeypatch: pytest.MonkeyPatch, returncode: int, stdout: str, state: JobState
) -> None:
    launchctl_answers(monkeypatch, returncode, stdout)

    assert LiveHost().job("io.github.thewisepup.computer-history.ingest") == state


def test_build_without_uv_is_a_host_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(live.shutil, "which", lambda _: None)

    with pytest.raises(HostError, match="uv is not installed"):
        LiveHost().build("abc123", tmp_path / "venv")

    assert not (tmp_path / "venv").exists()
