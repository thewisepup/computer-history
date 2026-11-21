from __future__ import annotations

import plistlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from computer_history.host import OPEN_ACTIVITYWATCH, Host, HostError, JobBusy, JobState
from computer_history.stable.layout import CAPTURE_AGENT_LABEL, LABEL_PREFIX, Layout

STOPGAP_LABEL = f"{LABEL_PREFIX}.backend"
RESTART_THROTTLE_SECONDS = 30
WATCHDOG_INTERVAL_SECONDS = 60
DISCARDED = "/dev/null"
UNLOAD_POLL_SECONDS = 0.1
UNLOAD_WAIT_SECONDS = 5.0
LOAD_ATTEMPTS = 3
LOAD_RETRY_SECONDS = 0.5


class Schedule(Enum):
    KEEP_ALIVE = "keep alive"  # run at load, restarted by launchd when it exits
    EVERY_MINUTE = "every minute"  # run at load, then once a minute
    AT_LOAD = "at load"  # run once at load


@dataclass(frozen=True)
class LaunchAgent:
    """A LaunchAgent the stable install runs: the current version's command with these arguments.

    A program, when given, runs instead of the command, and stdout goes to the log unless quiet.
    """

    name: str
    label: str
    arguments: tuple[str, ...]
    schedule: Schedule = Schedule.KEEP_ALIVE
    program: tuple[str, ...] | None = None
    quiet: bool = False

    def plist(self, layout: Layout) -> Path:
        return layout.launch_agents / f"{self.label}.plist"

    def render(self, layout: Layout) -> bytes:
        """The plist: run at load, then kept alive or rerun as its schedule says."""
        log = str(layout.logs / f"{self.name}.log")
        command = self.program or (str(layout.command(layout.current)), *self.arguments)
        plist: dict[str, object] = {
            "Label": self.label,
            "ProgramArguments": list(command),
            "RunAtLoad": True,
            "StandardOutPath": DISCARDED if self.quiet else log,
            "StandardErrorPath": log,
        }
        if self.schedule is Schedule.KEEP_ALIVE:
            plist |= {"KeepAlive": True, "ThrottleInterval": RESTART_THROTTLE_SECONDS}
        elif self.schedule is Schedule.EVERY_MINUTE:
            plist["StartInterval"] = WATCHDOG_INTERVAL_SECONDS
        return plistlib.dumps(plist)


BACKEND = LaunchAgent("backend", f"{LABEL_PREFIX}.ingest", ("ingest", "--watch"))
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
STABLE_AGENTS = (BACKEND, WATCHDOG, ACTIVITYWATCH_AT_LOGIN)


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
    """Write the agent's plist and load it, first booting out and waiting out the loaded copy."""
    layout.launch_agents.mkdir(parents=True, exist_ok=True)
    layout.logs.mkdir(parents=True, exist_ok=True)
    plist = agent.plist(layout)
    plist.write_bytes(agent.render(layout))
    if host.job(agent.label).loaded:
        host.unload(agent.label)
        _wait_until_unloaded(host, agent.label, sleep)
    for attempt in range(1, LOAD_ATTEMPTS + 1):
        try:
            host.load(plist)
            return
        except JobBusy:
            if attempt == LOAD_ATTEMPTS:
                raise
            sleep(LOAD_RETRY_SECONDS)


def _wait_until_unloaded(host: Host, label: str, sleep: Callable[[float], None]) -> None:
    for _ in range(round(UNLOAD_WAIT_SECONDS / UNLOAD_POLL_SECONDS)):
        if not host.job(label).loaded:
            return
        sleep(UNLOAD_POLL_SECONDS)
    raise HostError(f"{label} was still loaded {UNLOAD_WAIT_SECONDS:g}s after booting it out")


def remove_agent(host: Host, label: str, plist: Path) -> bool:
    """Boot out a LaunchAgent and delete its plist; returns whether there was anything to remove."""
    found = plist.exists()
    if host.job(label).loaded:
        host.unload(label)
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
