"""A host adapter for tests: records every call and plays back scripted answers."""

from __future__ import annotations

import plistlib
import shutil
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path

import computer_history.store
from computer_history.host import CheckOutcome, CheckRun, GitState, HostError, JobBusy, JobState
from computer_history.sources import IngestHealth, write_health
from computer_history.stable import (
    BACKEND,
    PACKAGES_FILE_NAME,
    RELEASE_GATE,
    STOPGAP_LABEL,
    Layout,
)

FAKE_PYTHON = "python3.12"
MIGRATIONS = Path(computer_history.store.__file__).parent / "migrations"
OFFLINE = "could not list main's newest commits from GitHub: offline"
NOT_A_CHECKOUT = "could not read the checkout's HEAD: fatal: not a git repository"


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


BackendStart = Callable[["FakeHost"], None]


def completes_a_cycle(
    health: Path, *, error: str | None = None, sources_unavailable: bool = False
) -> BackendStart:
    """A backend that runs its first ingest cycle at once, failing with the error if given one."""

    def start(_: FakeHost) -> None:
        now = datetime.now(UTC)
        if error is None:
            write_health(health, IngestHealth(now, last_success_at=now))
            return
        cycle = IngestHealth(now, 1, now, last_error=error, sources_unavailable=sources_unavailable)
        write_health(health, cycle)

    return start


def then(first: BackendStart, *later: BackendStart) -> BackendStart:
    """A backend that does first at start, then each later step at the next lookups of it."""

    def start(host: FakeHost) -> None:
        first(host)
        host.later.extend(later)

    return start


def crashes(host: FakeHost) -> None:
    """A backend whose process exits after launchd is first asked about it."""
    host.crashing = True


def stays_silent(_: FakeHost) -> None:
    """A backend that runs but never completes a cycle."""


class FakeHost:
    """Commits, check runs and the checkout's git state as scripted, a build that lays out a venv,
    launchd as a dict, the backend's starts as scripted, and ActivityWatch's app and notifications
    as flags and a list.

    A booted-out job can stay loaded for a few more lookups or loads (which fail busy meanwhile),
    and loads can fail busy first.
    """

    def __init__(
        self,
        *,
        checks: Mapping[str, list[CheckRun]] | None = None,
        loaded: Iterable[str] = (),
        offline: bool = False,
        git: GitState | None = None,
        build_error: str | None = None,
        build_blocks_packages: bool = False,
        job_error: str | None = None,
        unload_lingers: int = 0,
        busy_loads: int = 0,
        backend_starts: Iterable[BackendStart] = (),
        activitywatch_running: bool = True,
        opening_starts_activitywatch: bool = True,
        notify_error: str | None = None,
    ) -> None:
        self.checks = dict(checks or {})
        self.jobs = {label: JobState(loaded=True, pid=100 + n) for n, label in enumerate(loaded)}
        self.offline = offline
        self.git = git
        self.off_main: dict[str, list[CheckRun]] = {}
        self.build_error = build_error
        self.build_blocks_packages = build_blocks_packages
        self.job_error = job_error
        self.unload_lingers = unload_lingers
        self.busy_loads = busy_loads
        self.lingering: dict[str, int] = {}
        self.backend_starts = list(backend_starts)
        self.crashing = False
        self.later: list[BackendStart] = []
        self.running_activitywatch = activitywatch_running
        self.opening_starts_activitywatch = opening_starts_activitywatch
        self.notify_error = notify_error
        self.notifications: list[str] = []
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
        return (self.checks | self.off_main)[commit]

    def git_state(self, checkout: Path) -> GitState:
        self.calls.append(("git_state", str(checkout)))
        if self.git is None:
            raise HostError(NOT_A_CHECKOUT)
        return self.git

    def build(self, commit: str, venv: Path) -> str:
        self.calls.append(("build", commit))
        (venv / "bin").mkdir(parents=True)
        if self.build_error is not None:
            raise HostError(self.build_error)
        (venv / "bin" / "computer-history").write_text("#!/bin/sh\n")
        installed_package(venv).mkdir(parents=True)
        shutil.copytree(MIGRATIONS, installed_package(venv) / "store" / "migrations")
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
        if label == BACKEND.label and self.later:
            self.later.pop(0)(self)
        state = self.jobs.get(label, JobState(loaded=False))
        if label == BACKEND.label and self.crashing and state.loaded:
            self.crashing = False
            self.jobs[label] = JobState(loaded=True)
        return state

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
        if label == BACKEND.label and self.backend_starts:
            self.backend_starts.pop(0)(self)

    def unload(self, label: str) -> None:
        self.calls.append(("unload", label))
        if self.jobs.pop(label, None) is None:
            raise HostError(f"{label} is not loaded")
        self.lingering[label] = self.unload_lingers

    def activitywatch_running(self) -> bool:
        self.calls.append(("activitywatch_running", ""))
        return self.running_activitywatch

    def open_activitywatch(self) -> None:
        self.calls.append(("open_activitywatch", ""))
        if self.opening_starts_activitywatch:
            self.running_activitywatch = True

    def notify(self, message: str) -> None:
        self.calls.append(("notify", message))
        if self.notify_error is not None:
            raise HostError(self.notify_error)
        self.notifications.append(message)
