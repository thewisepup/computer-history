from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum, auto

from computer_history.host import Host, HostError
from computer_history.stable.launch_agents import LaunchAgent, load_agent, start_agent, stop_agent
from computer_history.stable.layout import Layout
from computer_history.transitions import TransitionTable


class AgentStop(Enum):
    RUNNING = auto()
    STOPPED_OWED = auto()
    RESTARTED = auto()


AGENT_STOPS = TransitionTable(
    "stopped agent",
    {
        AgentStop.RUNNING: frozenset({AgentStop.STOPPED_OWED, AgentStop.RESTARTED}),
        AgentStop.STOPPED_OWED: frozenset({AgentStop.STOPPED_OWED, AgentStop.RESTARTED}),
        AgentStop.RESTARTED: frozenset({AgentStop.STOPPED_OWED, AgentStop.RESTARTED}),
    },
)


class AgentNotStopped(HostError):
    """An agent could not be stopped, or launchd could not say whether it was loaded."""

    def __init__(self, agent: LaunchAgent, cause: HostError) -> None:
        super().__init__(str(cause))
        self.agent = agent


@dataclass(frozen=True)
class Restart:
    """The agents started again, in the order they were started, and each one that failed, why."""

    agents: tuple[LaunchAgent, ...]
    failed: tuple[tuple[LaunchAgent, HostError], ...] = ()


class StoppedAgents:
    """The LaunchAgents an operation stopped for a step, and owes a start once the step is done.

    An agent is owed a start from the moment its stop begins, so one whose stop failed is owed too.
    """

    def __init__(
        self, host: Host, layout: Layout, *, sleep: Callable[[float], None] = time.sleep
    ) -> None:
        self._host = host
        self._layout = layout
        self._sleep = sleep
        self._stops: dict[LaunchAgent, AgentStop] = {}

    def stop(self, agents: Iterable[LaunchAgent]) -> None:
        """Stop each agent launchd has loaded, in order, waiting until launchd lets it go."""
        for agent in agents:
            try:
                if not self._host.job(agent.label).loaded:
                    continue
                self._move(agent, AgentStop.STOPPED_OWED)
                stop_agent(self._host, agent.label, sleep=self._sleep)
            except HostError as exc:
                raise AgentNotStopped(agent, exc) from exc

    def start_again(self) -> Restart:
        """Start every owed agent from its plist, the last stopped first.

        A failed start counts unless launchd answers that the agent is loaded.
        """
        return self._start_owed(skip_loaded=False)

    def start_again_unless_loaded(self) -> Restart:
        """Start the owed agents launchd no longer has loaded, the last stopped first.

        An agent launchd gives no answer about is left alone.
        """
        return self._start_owed(skip_loaded=True)

    def load(self, agent: LaunchAgent) -> None:
        """Write the agent's plist and load it, stopped or not; it is no longer owed a start."""
        load_agent(self._host, self._layout, agent, sleep=self._sleep)
        self._move(agent, AgentStop.RESTARTED)

    def _move(self, agent: LaunchAgent, target: AgentStop) -> None:
        current = self._stops.get(agent, AgentStop.RUNNING)
        if AGENT_STOPS.move(current, target) is not current:
            self._stops.pop(agent, None)
        self._stops[agent] = target

    def _start_owed(self, *, skip_loaded: bool) -> Restart:
        owed = tuple(
            agent for agent, stop in reversed(self._stops.items()) if stop is AgentStop.STOPPED_OWED
        )
        for agent in owed:
            self._move(agent, AgentStop.RESTARTED)
        failed: list[tuple[LaunchAgent, HostError]] = []
        for agent in owed:
            if skip_loaded and self._loaded(agent, unanswered=True):
                continue
            try:
                start_agent(self._host, agent.plist(self._layout), sleep=self._sleep)
            except HostError as exc:
                if skip_loaded or not self._loaded(agent, unanswered=False):
                    failed.append((agent, exc))
        return Restart(owed, tuple(failed))

    def _loaded(self, agent: LaunchAgent, *, unanswered: bool) -> bool:
        try:
            return self._host.job(agent.label).loaded
        except HostError:
            return unanswered
