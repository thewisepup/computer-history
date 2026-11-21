from __future__ import annotations

import plistlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import time as clock_time
from enum import Enum
from pathlib import Path

from computer_history.host import OPEN_ACTIVITYWATCH, Host, HostError, JobBusy, JobState
from computer_history.stable.layout import CAPTURE_AGENT_LABEL, LABEL_PREFIX, Layout

STOPGAP_LABEL = f"{LABEL_PREFIX}.backend"
RESTART_THROTTLE_SECONDS = 30
DAILY_BACKUP_HOUR = 3
EVERY_MINUTE_SECONDS = 60
DISCARDED = "/dev/null"
UNLOAD_POLL_SECONDS = 0.1
UNLOAD_WAIT_SECONDS = 5.0
LOAD_ATTEMPTS = 3
LOAD_RETRY_SECONDS = 0.5


class Schedule(Enum):
    KEEP_ALIVE = "keep alive"  # run at load, restarted by launchd when it exits
    EVERY_MINUTE = "every minute"  # run at load, then once a minute
    DAILY = "daily"  # run at load, then at its daily time
    AT_LOAD = "at load"  # run once at load


@dataclass(frozen=True)
class LaunchAgent:
    """A LaunchAgent the stable install runs: the current command or a program, on a schedule."""

    name: str
    label: str
    arguments: tuple[str, ...]
    schedule: Schedule = Schedule.KEEP_ALIVE
    daily_at: clock_time | None = None
    program: tuple[str, ...] | None = None
    quiet: bool = False

    def plist(self, layout: Layout) -> Path:
        return layout.launch_agents / f"{self.label}.plist"

    def render(self, layout: Layout) -> bytes:
        """The plist: run at load, then kept alive, or rerun as its schedule says."""
        log = str(layout.logs / f"{self.name}.log")
        command = self.program or (str(layout.command(layout.current)), *self.arguments)
        plist: dict[str, object] = {
            "Label": self.label,
            "ProgramArguments": list(command),
            "RunAtLoad": True,
            "StandardOutPath": DISCARDED if self.quiet else log,
            "StandardErrorPath": log,
        }
        match self.schedule:
            case Schedule.KEEP_ALIVE:
                plist |= {"KeepAlive": True, "ThrottleInterval": RESTART_THROTTLE_SECONDS}
            case Schedule.EVERY_MINUTE:
                plist["StartInterval"] = EVERY_MINUTE_SECONDS
            case Schedule.DAILY:
                at = self.daily_at or clock_time()
                plist["StartCalendarInterval"] = {"Hour": at.hour, "Minute": at.minute}
            case Schedule.AT_LOAD:
                pass
        return plistlib.dumps(plist)


BACKEND = LaunchAgent("backend", f"{LABEL_PREFIX}.ingest", ("ingest", "--watch"))
DAILY_BACKUP = LaunchAgent(
    "backup",
    f"{LABEL_PREFIX}.backup",
    ("backup",),
    Schedule.DAILY,
    daily_at=clock_time(DAILY_BACKUP_HOUR),
)
WATCHDOG = LaunchAgent(
    "watchdog", f"{LABEL_PREFIX}.watchdog", ("watchdog",), Schedule.EVERY_MINUTE, quiet=True
)
ACTIVITYWATCH_AT_LOGIN = LaunchAgent(
    "activitywatch",
    f"{LABEL_PREFIX}.activitywatch",
    (),
    Schedule.AT_LOAD,
    program=OPEN_ACTIVITYWATCH,
)
STABLE_AGENTS = (BACKEND, DAILY_BACKUP, WATCHDOG, ACTIVITYWATCH_AT_LOGIN)


@dataclass(frozen=True)
class AgentStatus:
    """A LaunchAgent status reports on: whether its plist is installed and what launchd says.

    The state is None when launchd was not asked; retired marks the stopgap backend.
    """

    name: str
    label: str
    installed: bool
    state: JobState | None
    retired: bool = False


def load_agent(
    host: Host, layout: Layout, agent: LaunchAgent, *, sleep: Callable[[float], None] = time.sleep
) -> None:
    """Write the agent's plist and load it, first booting out and waiting out the loaded copy.

    An agent that runs only at load stays as it is when it is loaded from the same plist.
    """
    layout.launch_agents.mkdir(parents=True, exist_ok=True)
    layout.logs.mkdir(parents=True, exist_ok=True)
    plist = agent.plist(layout)
    rendered = agent.render(layout)
    loaded = host.job(agent.label).loaded
    if loaded and agent.schedule is Schedule.AT_LOAD and _holds(plist, rendered):
        return
    plist.write_bytes(rendered)
    if loaded:
        stop_agent(host, agent.label, sleep=sleep)
    start_agent(host, plist, sleep=sleep)


def _holds(plist: Path, rendered: bytes) -> bool:
    return plist.is_file() and plist.read_bytes() == rendered


def stop_agent(host: Host, label: str, *, sleep: Callable[[float], None] = time.sleep) -> None:
    """Boot a loaded LaunchAgent out and wait until launchd no longer has it."""
    host.unload(label)
    for _ in range(round(UNLOAD_WAIT_SECONDS / UNLOAD_POLL_SECONDS)):
        if not host.job(label).loaded:
            return
        sleep(UNLOAD_POLL_SECONDS)
    raise HostError(f"{label} was still loaded {UNLOAD_WAIT_SECONDS:g}s after booting it out")


def stop_if_loaded(host: Host, label: str, *, sleep: Callable[[float], None] = time.sleep) -> bool:
    """Boot a LaunchAgent out if launchd has it loaded; returns whether it was loaded."""
    if not host.job(label).loaded:
        return False
    stop_agent(host, label, sleep=sleep)
    return True


def start_agent(host: Host, plist: Path, *, sleep: Callable[[float], None] = time.sleep) -> None:
    """Load a LaunchAgent's plist, trying again while launchd is still busy with an earlier copy."""
    for attempt in range(1, LOAD_ATTEMPTS + 1):
        try:
            host.load(plist)
            return
        except JobBusy:
            if attempt == LOAD_ATTEMPTS:
                raise
            sleep(LOAD_RETRY_SECONDS)


def remove_agent(
    host: Host, label: str, plist: Path, *, sleep: Callable[[float], None] = time.sleep
) -> bool:
    """Boot out a LaunchAgent, wait until launchd no longer has it, and delete its plist.

    Returns whether there was anything to remove.
    """
    found = plist.exists()
    if stop_if_loaded(host, label, sleep=sleep):
        found = True
    plist.unlink(missing_ok=True)
    return found


def stopgap_plist(layout: Layout) -> Path:
    return layout.launch_agents / f"{STOPGAP_LABEL}.plist"


def agent_statuses(host: Host, layout: Layout) -> list[AgentStatus]:
    """The stable install's agents, the capture agent and the stopgap backend, as launchd sees them.

    Only agents with a plist are looked up, and the stopgap whenever the live folder exists.
    """
    statuses = [
        _status(host, agent.name, agent.label, agent.plist(layout).exists())
        for agent in STABLE_AGENTS
    ]
    statuses.append(
        _status(host, "capture agent", CAPTURE_AGENT_LABEL, layout.capture_agent_plist.exists())
    )
    stopgap = stopgap_plist(layout).exists()
    state = host.job(STOPGAP_LABEL) if stopgap or layout.live.exists() else None
    statuses.append(AgentStatus("stopgap backend", STOPGAP_LABEL, stopgap, state, retired=True))
    return statuses


def _status(host: Host, name: str, label: str, installed: bool) -> AgentStatus:
    return AgentStatus(name, label, installed, host.job(label) if installed else None)
