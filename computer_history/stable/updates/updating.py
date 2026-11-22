from __future__ import annotations

import shutil
import signal
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from types import FrameType

from computer_history.host import Host, HostError
from computer_history.stable.gate import GateVerdict, newest_passing, none_passed
from computer_history.stable.launch_agents import BACKEND, load_agent
from computer_history.stable.layout import NOTHING_CHANGED, Layout
from computer_history.stable.update_log import UpdateAction, UpdateLogEntry, append_or_note
from computer_history.stable.updates.falling_back import fall_back
from computer_history.stable.updates.preparing import Prepared, UpdateFailed, prepare
from computer_history.stable.updates.waiting import (
    FIRST_CYCLE_WAIT_SECONDS,
    LastCycle,
    wait_for_first_cycle,
)
from computer_history.stable.versions import InstalledVersion, point, pointed, version_name
from computer_history.store import DatabaseCopy

INTERRUPTED = "the update was interrupted before the backend's first ingest cycle"
INTERRUPTING_SIGNALS = (signal.SIGINT, signal.SIGTERM)


@dataclass(frozen=True)
class UpdateReport:
    """What update did (no action when already up to date), its versions, backup and problems."""

    action: UpdateAction | None
    commit: str
    kept: str
    skipped: tuple[GateVerdict, ...] = ()
    behind: bool = False
    backup: DatabaseCopy | None = None
    reason: str | None = None
    restored: Path | None = None
    removed: Path | None = None
    interrupted: bool = False
    problems: tuple[str, ...] = ()

    @property
    def version(self) -> str:
        return version_name(self.commit)


@dataclass(frozen=True)
class FirstCycle:
    """How the switch to the new version ended: no problem, or why to fall back."""

    problem: str | None
    interrupted: bool = False


def update(
    host: Host,
    layout: Layout,
    *,
    last_cycle: LastCycle,
    now: Callable[[], datetime],
    wait_seconds: float = FIRST_CYCLE_WAIT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> UpdateReport:
    """Move current to the newest main commit the release gate passes, falling back on its own.

    The backend restarts on it with spool deletion held; a crash, a failed cycle, none in time or
    Ctrl-C (or SIGTERM) puts the old version back, and the fallback itself runs to its end.
    """
    old = pointed(layout.current)
    if old is None:
        raise UpdateFailed(f"there is no stable install in {layout.live}; run install first")
    try:
        search = newest_passing(host)
    except HostError as exc:
        raise UpdateFailed(f"{exc} ({NOTHING_CHANGED})") from exc
    if search.chosen is None:
        raise UpdateFailed(f"{none_passed(search.skipped)} ({NOTHING_CHANGED})")
    commit = search.chosen.commit
    behind = any(version_name(verdict.commit) == old.name for verdict in search.skipped)
    if behind or version_name(commit) == old.name:
        return UpdateReport(None, commit, old.name, search.skipped, behind=behind)
    with _signals_interrupt():
        prepared = prepare(host, layout, commit, old, now=now, sleep=sleep)
        first = _switch(
            host,
            layout,
            prepared,
            last_cycle,
            now=now,
            wait_seconds=wait_seconds,
            sleep=sleep,
            monotonic=monotonic,
        )
    with _signals_deferred() as deferred:
        report = _finish(host, layout, prepared, first, commit, search.skipped, now, sleep)
    if deferred:
        report = replace(report, interrupted=True)
    return report


def _finish(
    host: Host,
    layout: Layout,
    prepared: Prepared,
    first: FirstCycle,
    commit: str,
    skipped: tuple[GateVerdict, ...],
    now: Callable[[], datetime],
    sleep: Callable[[float], None],
) -> UpdateReport:
    old = prepared.old
    if first.problem is not None:
        fell_back = fall_back(host, layout, prepared, first.problem, now=now, sleep=sleep)
        return UpdateReport(
            UpdateAction.FELL_BACK,
            commit,
            old.name,
            skipped,
            backup=prepared.backup,
            reason=first.problem,
            restored=fell_back.restored,
            interrupted=first.interrupted,
            problems=fell_back.problems,
        )
    problems: list[str] = []
    try:
        prepared.hold.release()
    except OSError as exc:
        problems.append(f"the spool hold {prepared.hold.path} could not be removed: {exc}")
    removed = _remove_version(layout, prepared.old_previous, keep=(prepared.new, old.name))
    entry = UpdateLogEntry(now(), UpdateAction.UPDATED, old.name, prepared.new)
    append_or_note(layout.update_log, entry, problems)
    return UpdateReport(
        UpdateAction.UPDATED,
        commit,
        old.name,
        skipped,
        backup=prepared.backup,
        removed=removed,
        problems=tuple(problems),
    )


def _switch(
    host: Host,
    layout: Layout,
    prepared: Prepared,
    last_cycle: LastCycle,
    *,
    now: Callable[[], datetime],
    wait_seconds: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
) -> FirstCycle:
    try:
        try:
            point(layout.previous, prepared.old.name)
            point(layout.current, prepared.new)
            started_at = now()
            load_agent(host, layout, BACKEND, sleep=sleep)
        except (HostError, OSError) as exc:
            return FirstCycle(f"the backend could not be started on the new version: {exc}")
        problem = wait_for_first_cycle(
            host, last_cycle, started_at, wait_seconds=wait_seconds, monotonic=monotonic
        )
    except KeyboardInterrupt:
        return FirstCycle(INTERRUPTED, interrupted=True)
    return FirstCycle(problem)


def _remove_version(
    layout: Layout, version: InstalledVersion | None, *, keep: tuple[str, ...]
) -> Path | None:
    if version is None or version.name in keep:
        return None
    folder = layout.versions / version.name
    shutil.rmtree(folder, ignore_errors=True)
    return folder


@contextmanager
def _signals_interrupt() -> Generator[None]:
    """Ctrl-C and SIGTERM raise KeyboardInterrupt while the update prepares and waits."""

    def interrupt(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    with _handling(interrupt):
        yield


@contextmanager
def _signals_deferred() -> Generator[list[int]]:
    """Ctrl-C and SIGTERM are only noted while a fallback or the update's last steps run."""
    received: list[int] = []

    def note(signum: int, frame: FrameType | None) -> None:
        received.append(signum)

    with _handling(note):
        yield received


@contextmanager
def _handling(handler: Callable[[int, FrameType | None], None]) -> Generator[None]:
    try:
        previous = [(signum, signal.signal(signum, handler)) for signum in INTERRUPTING_SIGNALS]
    except ValueError:
        yield
        return
    try:
        yield
    finally:
        for signum, before in previous:
            signal.signal(signum, before)
