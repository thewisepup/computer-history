from __future__ import annotations

from pathlib import Path

import pytest

from computer_history.host import JobState
from computer_history.stable import launch_agents
from computer_history.stable.launch_agents import (
    BACKEND,
    DAILY_BACKUP,
    LOAD_ATTEMPTS,
    WATCHDOG,
    LaunchAgent,
)
from computer_history.stable.layout import Layout
from computer_history.stable.stopped_agents import AgentNotStopped, StoppedAgents
from tests.fake_host import FakeHost

AGENTS = (DAILY_BACKUP, WATCHDOG, BACKEND)
LAUNCHD_DOWN = "could not ask launchd about it: launchctl timed out"


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    layout = Layout(tmp_path / "live", tmp_path / "home")
    layout.launch_agents.mkdir(parents=True)
    for agent in AGENTS:
        agent.plist(layout).write_bytes(agent.render(layout))
    return layout


@pytest.fixture(autouse=True)
def quick_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(launch_agents, "UNLOAD_WAIT_SECONDS", 0.2)


def no_sleep(_: float) -> None:
    pass


def stopped_agents(host: FakeHost, layout: Layout) -> StoppedAgents:
    return StoppedAgents(host, layout, sleep=no_sleep)


def launchd_calls(host: FakeHost) -> list[tuple[str, str]]:
    return [(call, label) for call, label in host.calls if call in ("load", "unload")]


def loaded(host: FakeHost, agent: LaunchAgent) -> bool:
    return agent.label in host.jobs


def test_only_loaded_agents_are_stopped_and_they_start_again_the_last_stopped_first(
    layout: Layout,
) -> None:
    host = FakeHost(loaded=[DAILY_BACKUP.label, BACKEND.label])
    stopped = stopped_agents(host, layout)

    stopped.stop(AGENTS)

    assert stopped.owed == (DAILY_BACKUP, BACKEND)
    assert host.jobs == {}
    restart = stopped.start_again()
    assert restart.agents == (BACKEND, DAILY_BACKUP)
    assert restart.failed == ()
    assert launchd_calls(host) == [
        ("unload", DAILY_BACKUP.label),
        ("unload", BACKEND.label),
        ("load", BACKEND.label),
        ("load", DAILY_BACKUP.label),
    ]
    assert stopped.owed == ()
    assert not loaded(host, WATCHDOG)


def test_a_stop_waits_until_launchd_lets_go_and_a_busy_start_is_tried_again(
    layout: Layout,
) -> None:
    host = FakeHost(loaded=[BACKEND.label], unload_lingers=1, busy_loads=LOAD_ATTEMPTS - 1)
    stopped = stopped_agents(host, layout)

    stopped.stop((BACKEND,))
    restart = stopped.start_again_unless_loaded()

    assert restart.failed == ()
    assert loaded(host, BACKEND)
    assert [call for call, _ in launchd_calls(host)] == ["unload", *["load"] * LOAD_ATTEMPTS]


def test_an_agent_that_will_not_stop_is_still_owed_a_start(layout: Layout) -> None:
    host = FakeHost(loaded=[DAILY_BACKUP.label, BACKEND.label])
    stopped = stopped_agents(host, layout)
    stopped.stop((DAILY_BACKUP,))
    host.unload_lingers = 3

    with pytest.raises(AgentNotStopped) as raised:
        stopped.stop((BACKEND,))

    assert raised.value.agent is BACKEND
    assert str(raised.value).startswith(f"{BACKEND.label} was still loaded ")
    assert stopped.owed == (DAILY_BACKUP, BACKEND)


def test_starting_again_tries_an_agent_whose_stop_failed_once_launchd_lets_it_go(
    layout: Layout,
) -> None:
    host = FakeHost(loaded=[BACKEND.label], unload_lingers=3)
    stopped = stopped_agents(host, layout)
    with pytest.raises(AgentNotStopped):
        stopped.stop((BACKEND,))

    restart = stopped.start_again()

    assert restart.failed == ()
    assert loaded(host, BACKEND)


def test_starting_again_unless_loaded_leaves_an_agent_launchd_still_has(layout: Layout) -> None:
    host = FakeHost(loaded=[BACKEND.label], unload_lingers=3)
    stopped = stopped_agents(host, layout)
    with pytest.raises(AgentNotStopped):
        stopped.stop((BACKEND,))

    restart = stopped.start_again_unless_loaded()

    assert restart.failed == ()
    assert [call for call, _ in launchd_calls(host)] == ["unload"]


def test_an_agent_launchd_cannot_be_asked_about_is_not_owed_and_those_before_it_are(
    layout: Layout,
) -> None:
    host = FakeHost(loaded=[DAILY_BACKUP.label, BACKEND.label])
    stopped = stopped_agents(host, layout)
    stopped.stop((DAILY_BACKUP,))
    host.job_error = LAUNCHD_DOWN

    with pytest.raises(AgentNotStopped) as raised:
        stopped.stop((BACKEND,))

    assert raised.value.agent is BACKEND
    assert str(raised.value) == LAUNCHD_DOWN
    assert stopped.owed == (DAILY_BACKUP,)
    assert loaded(host, BACKEND)


def test_a_start_that_keeps_failing_is_reported(layout: Layout) -> None:
    for start_again in (StoppedAgents.start_again, StoppedAgents.start_again_unless_loaded):
        host = FakeHost(loaded=[BACKEND.label])
        stopped = stopped_agents(host, layout)
        stopped.stop((BACKEND,))
        host.busy_loads = LOAD_ATTEMPTS

        restart = start_again(stopped)

        assert [(agent, str(exc)) for agent, exc in restart.failed] == [
            (
                BACKEND,
                f"could not load {BACKEND.plist(layout)}: Bootstrap failed: 5: Input/output error",
            )
        ]
        assert not loaded(host, BACKEND)


def test_a_failed_start_of_an_agent_launchd_confirms_loaded_is_no_failure(layout: Layout) -> None:
    host = FakeHost(loaded=[BACKEND.label])
    stopped = stopped_agents(host, layout)
    stopped.stop((BACKEND,))
    host.jobs[BACKEND.label] = JobState(loaded=True)

    restart = stopped.start_again()

    assert restart.agents == (BACKEND,)
    assert restart.failed == ()


def test_a_failed_start_launchd_cannot_confirm_counts_as_failed(layout: Layout) -> None:
    host = FakeHost(loaded=[BACKEND.label])
    stopped = stopped_agents(host, layout)
    stopped.stop((BACKEND,))
    host.busy_loads = LOAD_ATTEMPTS
    host.job_error = LAUNCHD_DOWN

    restart = stopped.start_again()

    assert [agent for agent, _ in restart.failed] == [BACKEND]


def test_starting_again_unless_loaded_tries_no_start_launchd_cannot_confirm_is_needed(
    layout: Layout,
) -> None:
    host = FakeHost(loaded=[BACKEND.label])
    stopped = stopped_agents(host, layout)
    stopped.stop((BACKEND,))
    host.job_error = LAUNCHD_DOWN

    restart = stopped.start_again_unless_loaded()

    assert restart.failed == ()
    assert [call for call, _ in launchd_calls(host)] == ["unload"]


def test_a_ctrl_c_during_the_step_still_starts_the_stopped_agents_again(layout: Layout) -> None:
    host = FakeHost(loaded=[DAILY_BACKUP.label, BACKEND.label])
    stopped = stopped_agents(host, layout)

    def step() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        try:
            stopped.stop(AGENTS)
            step()
        except BaseException:
            assert stopped.start_again_unless_loaded().failed == ()
            raise

    assert loaded(host, DAILY_BACKUP)
    assert loaded(host, BACKEND)


def test_a_ctrl_c_while_waiting_out_a_stop_leaves_the_agent_owed(layout: Layout) -> None:
    host = FakeHost(loaded=[BACKEND.label], unload_lingers=1)

    def interrupted(_: float) -> None:
        raise KeyboardInterrupt

    stopped = StoppedAgents(host, layout, sleep=interrupted)

    with pytest.raises(KeyboardInterrupt):
        stopped.stop((BACKEND,))

    assert stopped.owed == (BACKEND,)
    assert stopped.start_again_unless_loaded().failed == ()
    assert loaded(host, BACKEND)


def test_load_rewrites_the_plist_and_starts_an_agent_whether_or_not_it_was_stopped(
    layout: Layout,
) -> None:
    host = FakeHost(loaded=[BACKEND.label])
    stopped = stopped_agents(host, layout)
    stopped.stop((BACKEND,))
    BACKEND.plist(layout).write_bytes(b"stale")

    stopped.load(BACKEND)
    stopped.load(WATCHDOG)

    assert BACKEND.plist(layout).read_bytes() == BACKEND.render(layout)
    assert loaded(host, BACKEND)
    assert loaded(host, WATCHDOG)
    assert stopped.owed == ()
    assert stopped.start_again().agents == ()


def test_load_replaces_a_running_agent(layout: Layout) -> None:
    host = FakeHost(loaded=[BACKEND.label])

    stopped_agents(host, layout).load(BACKEND)

    assert launchd_calls(host) == [("unload", BACKEND.label), ("load", BACKEND.label)]
    assert loaded(host, BACKEND)
