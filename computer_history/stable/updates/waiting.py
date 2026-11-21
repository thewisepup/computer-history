from __future__ import annotations

import signal
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from types import FrameType
from typing import Protocol

from computer_history.host import Host, HostError
from computer_history.stable.launch_agents import BACKEND

FIRST_CYCLE_WAIT_SECONDS = 600.0
FIRST_CYCLE_POLL_SECONDS = 1.0
BACKEND_LOG_HINT = "see the backend's log"
INTERRUPTED = "the update was interrupted before the backend's first ingest cycle"


class BackendCycle(Protocol):
    """The backend's last completed ingest cycle, as its heartbeat records it."""

    @property
    def cycle_at(self) -> datetime: ...

    @property
    def ok(self) -> bool: ...

    @property
    def error(self) -> str | None: ...

    @property
    def sources_unavailable(self) -> bool: ...


LastCycle = Callable[[], BackendCycle | None]


@dataclass(frozen=True)
class FirstCycle:
    """How the wait for the backend's first cycle ended: no problem, or why to fall back."""

    problem: str | None
    interrupted: bool = False


def wait_for_first_cycle(
    host: Host,
    last_cycle: LastCycle,
    started_at: datetime,
    *,
    wait_seconds: float,
    sleep: Callable[[float], None] | None = None,
) -> FirstCycle:
    """Wait for an ok cycle since the backend started, through cycles whose sources were down."""
    try:
        with _terminate_as_interrupt():
            return FirstCycle(
                _wait(host, last_cycle, started_at, wait_seconds, sleep or time.sleep)
            )
    except KeyboardInterrupt:
        return FirstCycle(INTERRUPTED, interrupted=True)


def _wait(
    host: Host,
    last_cycle: LastCycle,
    started_at: datetime,
    wait_seconds: float,
    sleep: Callable[[float], None],
) -> str | None:
    seen_pid = None
    unavailable = None
    for _ in range(max(1, round(wait_seconds / FIRST_CYCLE_POLL_SECONDS))):
        cycle = _read(last_cycle)
        if cycle is not None and cycle.cycle_at >= started_at:
            if cycle.ok:
                return None
            if not cycle.sources_unavailable:
                return f"the backend's first ingest cycle failed: {cycle.error or BACKEND_LOG_HINT}"
            unavailable = cycle.error or BACKEND_LOG_HINT
        try:
            job = host.job(BACKEND.label)
        except HostError as exc:
            return f"launchd could not be asked about the backend: {exc}"
        if not job.loaded:
            return "the backend was no longer loaded"
        if seen_pid is not None and job.pid != seen_pid:
            return "the backend crashed before its first ingest cycle"
        seen_pid = job.pid
        sleep(FIRST_CYCLE_POLL_SECONDS)
    if unavailable is not None:
        waited = f"the whole {wait_seconds:g}s wait"
        return f"the backend's sources stayed unavailable for {waited}: {unavailable}"
    return f"the backend completed no ingest cycle within {wait_seconds:g}s"


def _read(last_cycle: LastCycle) -> BackendCycle | None:
    try:
        return last_cycle()
    except (OSError, ValueError):
        return None


@contextmanager
def _terminate_as_interrupt() -> Generator[None]:
    """While waiting, a SIGTERM stops the wait as Ctrl-C does."""

    def interrupt(signum: int, frame: FrameType | None) -> None:
        raise KeyboardInterrupt

    try:
        previous = signal.signal(signal.SIGTERM, interrupt)
    except ValueError:
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)
