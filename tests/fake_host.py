"""A host adapter for tests: records every call and plays back scripted answers."""

from __future__ import annotations

import plistlib
from collections.abc import Iterable, Mapping
from pathlib import Path

from computer_history.host import CheckOutcome, CheckRun, HostError, JobState
from computer_history.stable import RELEASE_GATE

FAKE_PYTHON = "python3.12"
OFFLINE = "could not read the checks from GitHub: offline"


def gate_runs(**outcomes: CheckOutcome | None) -> list[CheckRun]:
    """Every release-gate check passed, except the ones named (None leaves a check out)."""
    named = {name: CheckOutcome.SUCCESS for name in RELEASE_GATE} | outcomes
    return [CheckRun(name, outcome) for name, outcome in named.items() if outcome is not None]


def installed_package(venv: Path) -> Path:
    """Where a built environment holds the computer_history package."""
    return venv / "lib" / FAKE_PYTHON / "site-packages" / "computer_history"


class FakeHost:
    """Commits and check runs as scripted, a build that lays out a venv, and launchd as a dict."""

    def __init__(
        self,
        *,
        checks: Mapping[str, list[CheckRun]] | None = None,
        loaded: Iterable[str] = (),
        offline: bool = False,
        build_error: str | None = None,
    ) -> None:
        self.checks = dict(checks or {})
        self.jobs = {label: JobState(loaded=True, pid=100 + n) for n, label in enumerate(loaded)}
        self.offline = offline
        self.build_error = build_error
        self.calls: list[tuple[str, str]] = []

    def main_commits(self, limit: int) -> list[str]:
        self.calls.append(("main_commits", str(limit)))
        if self.offline:
            raise HostError(OFFLINE)
        return list(self.checks)[:limit]

    def check_runs(self, commit: str) -> list[CheckRun]:
        self.calls.append(("check_runs", commit))
        if self.offline:
            raise HostError(OFFLINE)
        return self.checks[commit]

    def build(self, commit: str, venv: Path) -> str:
        self.calls.append(("build", commit))
        (venv / "bin").mkdir(parents=True)
        if self.build_error is not None:
            raise HostError(self.build_error)
        (venv / "bin" / "computer-history").write_text("#!/bin/sh\n")
        installed_package(venv).mkdir(parents=True)
        return f"computer-history @ git+https://example.invalid/repo@{commit}\n"

    def job(self, label: str) -> JobState:
        self.calls.append(("job", label))
        return self.jobs.get(label, JobState(loaded=False))

    def load(self, plist: Path) -> None:
        label = str(plistlib.loads(plist.read_bytes())["Label"])
        self.calls.append(("load", label))
        if label in self.jobs:
            raise HostError(f"{label} is already loaded")
        self.jobs[label] = JobState(loaded=True, pid=200 + len(self.calls))

    def unload(self, label: str) -> None:
        self.calls.append(("unload", label))
        if self.jobs.pop(label, None) is None:
            raise HostError(f"{label} is not loaded")
