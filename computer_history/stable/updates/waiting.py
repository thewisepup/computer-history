from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Protocol

from computer_history.host import Host, HostError
from computer_history.stable.launch_agents import BACKEND

FIRST_CYCLE_WAIT_SECONDS = 600.0
FIRST_CYCLE_POLL_SECONDS = 1.0
BACKEND_LOG_HINT = "see the backend's log"


class BackendCycle(Protocol):
    """The backend's last completed ingest cycle, as its ingest health file records it."""

    @property
    def cycle_at(self) -> datetime: ...

    @property
    def ok(self) -> bool: ...

    @property
    def last_error(self) -> str | None: ...

    @property
    def sources_unavailable(self) -> bool: ...


LastCycle = Callable[[], BackendCycle | None]


def wait_for_first_cycle(
    host: Host,
    last_cycle: LastCycle,
    started_at: datetime,
    *,
    wait_seconds: float,
    sleep: Callable[[float], None] | None = None,
    monotonic: Callable[[], float] | None = None,
) -> str | None:
    """Wait until the deadline for an ok cycle since the backend started, through cycles whose
    sources were down; returns why to fall back, or None."""
    sleep = sleep or time.sleep
    monotonic = monotonic or time.monotonic
    deadline = monotonic() + wait_seconds
    seen_pid = None
    unavailable = None
    while True:
        cycle = _read(last_cycle)
        if cycle is not None and cycle.cycle_at >= started_at:
            if cycle.ok:
                return None
            why = cycle.last_error or BACKEND_LOG_HINT
            if not cycle.sources_unavailable:
                return f"the backend's first ingest cycle failed: {why}"
            unavailable = why
        try:
            job = host.job(BACKEND.label)
        except HostError as exc:
            return f"launchd could not be asked about the backend: {exc}"
        if not job.loaded:
            return "the backend was no longer loaded"
        if seen_pid is not None and job.pid != seen_pid:
            return "the backend crashed before its first ingest cycle"
        seen_pid = job.pid
        if monotonic() >= deadline:
            break
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
