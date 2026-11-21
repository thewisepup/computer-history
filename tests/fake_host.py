"""A host adapter for tests: records every call and plays back scripted answers."""

from __future__ import annotations

import plistlib
from collections.abc import Iterable, Mapping
from pathlib import Path

from computer_history.host import CheckOutcome, CheckRun, HostError, JobBusy, JobState
from computer_history.stable import PACKAGES_FILE_NAME, RELEASE_GATE, STOPGAP_LABEL, Layout

FAKE_PYTHON = "python3.12"
OFFLINE = "could not list main's newest commits from GitHub: offline"


def gate_runs(**outcomes: CheckOutcome | None) -> list[CheckRun]:
    """Every release-gate check passed, except the ones named (None leaves a check out)."""
    named = {name: CheckOutcome.SUCCESS for name in RELEASE_GATE} | outcomes
    return [CheckRun(name, outcome) for name, outcome in named.items() if outcome is not None]


def installed_package(venv: Path) -> Path:
    """Where a built environment holds the computer_history package."""
    return venv / "lib" / FAKE_PYTHON / "site-packages" / "computer_history"


def write_stopgap_plist(layout: Layout) -> Path:
    """Put the stopgap backend's plist where its hand-made install left it."""
    plist = layout.launch_agents / f"{STOPGAP_LABEL}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    plist.write_bytes(plistlib.dumps({"Label": STOPGAP_LABEL}))
    return plist


class FakeHost:
    """Commits and check runs as scripted, a build that lays out a venv, and launchd as a dict.

    A booted-out job can stay loaded for a few more lookups or loads (which fail busy meanwhile),
    and loads can fail busy first.
    """

    def __init__(
        self,
        *,
        checks: Mapping[str, list[CheckRun]] | None = None,
        loaded: Iterable[str] = (),
        offline: bool = False,
        build_error: str | None = None,
        build_blocks_packages: bool = False,
        job_error: str | None = None,
        unload_lingers: int = 0,
        busy_loads: int = 0,
    ) -> None:
        self.checks = dict(checks or {})
        self.jobs = {label: JobState(loaded=True, pid=100 + n) for n, label in enumerate(loaded)}
        self.offline = offline
        self.build_error = build_error
        self.build_blocks_packages = build_blocks_packages
        self.job_error = job_error
        self.unload_lingers = unload_lingers
        self.busy_loads = busy_loads
        self.lingering: dict[str, int] = {}
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
        if self.build_blocks_packages:
            (venv.parent / PACKAGES_FILE_NAME).mkdir()
        return f"computer-history @ git+https://example.invalid/repo@{commit}\n"

    def job(self, label: str) -> JobState:
        self.calls.append(("job", label))
        if self.job_error is not None:
            raise HostError(self.job_error)
        if self.lingering.get(label, 0) > 0:
            self.lingering[label] -= 1
            return JobState(loaded=True)
        return self.jobs.get(label, JobState(loaded=False))

    def load(self, plist: Path) -> None:
        label = str(plistlib.loads(plist.read_bytes())["Label"])
        self.calls.append(("load", label))
        if self.busy_loads > 0:
            self.busy_loads -= 1
            raise JobBusy(f"could not load {plist}: Bootstrap failed: 5: Input/output error")
        if self.lingering.get(label, 0) > 0:
            self.lingering[label] -= 1
            raise JobBusy(f"could not load {plist}: Bootstrap failed: 5: Input/output error")
        if label in self.jobs:
            raise HostError(f"{label} is already loaded")
        self.jobs[label] = JobState(loaded=True, pid=200 + len(self.calls))

    def unload(self, label: str) -> None:
        self.calls.append(("unload", label))
        if self.jobs.pop(label, None) is None:
            raise HostError(f"{label} is not loaded")
        self.lingering[label] = self.unload_lingers
