from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from computer_history.host import Host, HostError
from computer_history.stable.launch_agents import LaunchAgent, load_agent, start_agent, stop_agent
from computer_history.stable.layout import Layout


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
        self._owed: list[LaunchAgent] = []

    def stop(self, agents: Iterable[LaunchAgent]) -> None:
        """Stop each agent launchd has loaded, in order, waiting until launchd lets it go."""
        for agent in agents:
            try:
                if not self._host.job(agent.label).loaded:
                    continue
                if agent not in self._owed:
                    self._owed.append(agent)
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
        if agent in self._owed:
            self._owed.remove(agent)

    def _start_owed(self, *, skip_loaded: bool) -> Restart:
        owed = tuple(reversed(self._owed))
        self._owed.clear()
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
