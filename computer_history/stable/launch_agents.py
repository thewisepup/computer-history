from __future__ import annotations

import plistlib
from dataclasses import dataclass
from pathlib import Path

from computer_history.host import Host, JobState
from computer_history.stable.layout import Layout

LABEL_PREFIX = "io.github.thewisepup.computer-history"
STOPGAP_LABEL = f"{LABEL_PREFIX}.backend"
CAPTURE_AGENT_LABEL = f"{LABEL_PREFIX}.agent"
CAPTURE_AGENT_APP = "ComputerHistoryAgent.app"
RESTART_THROTTLE_SECONDS = 30


@dataclass(frozen=True)
class LaunchAgent:
    """A LaunchAgent the stable install runs: the current version's command with these arguments."""

    name: str
    label: str
    arguments: tuple[str, ...]

    def plist(self, layout: Layout) -> Path:
        return layout.launch_agents / f"{self.label}.plist"

    def render(self, layout: Layout) -> bytes:
        """The plist: run at load, restarted by launchd when it exits, at most once per throttle."""
        log = str(layout.logs / f"{self.name}.log")
        return plistlib.dumps(
            {
                "Label": self.label,
                "ProgramArguments": [str(layout.command(layout.current)), *self.arguments],
                "RunAtLoad": True,
                "KeepAlive": True,
                "ThrottleInterval": RESTART_THROTTLE_SECONDS,
                "StandardOutPath": log,
                "StandardErrorPath": log,
            }
        )


BACKEND = LaunchAgent("backend", f"{LABEL_PREFIX}.ingest", ("ingest", "--watch"))
STABLE_AGENTS = (BACKEND,)


@dataclass(frozen=True)
class AgentStatus:
    """A LaunchAgent status reports on, and launchd's state for it (None: no plist installed)."""

    name: str
    label: str
    plist: Path
    state: JobState | None


def load_agent(host: Host, layout: Layout, agent: LaunchAgent) -> None:
    """Write the agent's plist and load it, booting out the copy already loaded."""
    layout.launch_agents.mkdir(parents=True, exist_ok=True)
    layout.logs.mkdir(parents=True, exist_ok=True)
    plist = agent.plist(layout)
    plist.write_bytes(agent.render(layout))
    if host.job(agent.label).loaded:
        host.unload(agent.label)
    host.load(plist)


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

    Only an agent whose plist is installed is looked up in launchd.
    """
    capture_plist = (
        layout.home
        / "Applications"
        / CAPTURE_AGENT_APP
        / "Contents"
        / "Library"
        / "LaunchAgents"
        / f"{CAPTURE_AGENT_LABEL}.plist"
    )
    found = [(agent.name, agent.label, agent.plist(layout)) for agent in STABLE_AGENTS]
    found += [
        ("capture agent", CAPTURE_AGENT_LABEL, capture_plist),
        ("stopgap backend", STOPGAP_LABEL, stopgap_plist(layout)),
    ]
    return [
        AgentStatus(name, label, plist, host.job(label) if plist.exists() else None)
        for name, label, plist in found
    ]
