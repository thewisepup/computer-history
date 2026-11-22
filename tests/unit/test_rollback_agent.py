"""How rollback takes the capture agent back when the previous backend can't read its records."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cli_output import STATUS, RunCli, section
from fake_host import FakeHost, agent_built_from, completes_a_cycle, lay_out_agent
from stable_updates import (
    NEWER,
    OLDER,
    health,
    install_older,
    log_lines,
    stable_code,
    updating,
)

from computer_history.host import SpoolReads
from computer_history.sources import RECORD_KINDS, SPOOL_VERSION
from computer_history.stable import BACKEND, Layout, record_installed_agent, version_name
from computer_history.stable.updates import waiting

NEW, OLD = version_name(NEWER), version_name(OLDER)
WRITES_MORE = SpoolReads(SPOOL_VERSION, (*RECORD_KINDS, "heartbeat"))
NEXT_SPOOL = SpoolReads(SPOOL_VERSION + 1, RECORD_KINDS)
INSTALLED_AT = datetime(2026, 11, 21, tzinfo=UTC)


@pytest.fixture(autouse=True)
def quick_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(waiting, "FIRST_CYCLE_POLL_SECONDS", 0.001)


def carries_agent(layout: Layout, name: str, built_from: str) -> None:
    lay_out_agent(layout.agent_app(layout.versions / name), built_from)
    layout.agent_commit(layout.versions / name).write_text(f"{built_from}\n")


def updated_with_newer_agent(
    run: RunCli, live: Path, checkout: Path, newer_reads: SpoolReads = WRITES_MORE
) -> Layout:
    """OLDER updated to NEWER, whose agent was built and installed, OLDER's agent kept beside it."""
    layout = install_older(run, live, checkout)
    carries_agent(layout, OLD, OLDER)
    host = updating(
        layout,
        completes_a_cycle(health(layout)),
        spool_reads={NEWER: newer_reads},
        agent_trees={NEWER: "f" * 40},
    )
    assert run(stable_code(layout), "update", host=host)[0] == 0
    assert agent_built_from(layout.capture_agent_app) == NEWER
    return layout


def offline() -> FakeHost:
    """launchd answers; GitHub, the agent's source trees and builds are unreachable."""
    return FakeHost(
        offline=True,
        loaded=[BACKEND.label],
        agent_tree_error="could not read the agent's source tree from GitHub: offline",
        agent_build_error="could not download the commit: offline",
    )


def agent_calls(host: FakeHost) -> list[tuple[str, str]]:
    agent = ("agent_tree", "check_agent_toolchain", "build_agent", "install_agent")
    return [(call, arg) for call, arg in host.calls if call in agent]


def test_rollback_leaves_the_agent_when_the_previous_version_reads_all_it_writes(
    run: RunCli, live: Path, checkout: Path
) -> None:
    layout = updated_with_newer_agent(
        run, live, checkout, newer_reads=SpoolReads(SPOOL_VERSION, RECORD_KINDS)
    )
    record = layout.installed_agent.read_bytes()
    host = offline()

    code, out, err = run(stable_code(layout), "rollback", host=host)

    assert code == 0, err
    assert out[1:] == [
        f"Rolled back to version {OLD} from {NEW}",
        f"  previous      {NEW} (rollback again returns to it)",
        f"  agent         not moved ({OLD} reads every record kind it writes)",
        "  backend       restarted",
    ]
    assert agent_calls(host) == []
    assert agent_built_from(layout.capture_agent_app) == NEWER
    assert layout.installed_agent.read_bytes() == record
    assert [line["action"] for line in log_lines(layout)] == ["updated", "rolled back"]


@pytest.mark.parametrize(
    ("newer_reads", "reason"),
    [
        (WRITES_MORE, f"{OLD} does not read its heartbeat records"),
        (NEXT_SPOOL, f"{OLD} reads spool v{SPOOL_VERSION}, it writes v{SPOOL_VERSION + 1}"),
    ],
    ids=["new kind", "new spool version"],
)
def test_rollback_moves_the_agent_back_before_the_backend_restarts_when_it_writes_more(
    run: RunCli, live: Path, checkout: Path, newer_reads: SpoolReads, reason: str
) -> None:
    layout = updated_with_newer_agent(run, live, checkout, newer_reads)
    host = offline()

    code, out, err = run(stable_code(layout), "rollback", host=host)

    assert code == 0, err
    assert out[1:] == [
        f"Rolled back to version {OLD} from {NEW}",
        f"  previous      {NEW} (rollback again returns to it)",
        f"  agent         moved back to {OLD}'s build ({reason})",
        "  backend       restarted",
    ]
    install = ("install_agent", str(layout.agent_app(layout.versions / OLD)))
    assert agent_calls(host) == [install]
    assert host.calls.index(install) < host.calls.index(("unload", BACKEND.label))
    assert agent_built_from(layout.capture_agent_app) == OLDER
    assert json.loads(layout.installed_agent.read_text())["built_from"] == OLDER
    assert log_lines(layout)[1:] == [
        {
            "at": log_lines(layout)[1]["at"],
            "action": "agent rolled back",
            "from": NEW,
            "to": OLD,
            "reason": reason,
        },
        {
            "at": log_lines(layout)[2]["at"],
            "action": "rolled back",
            "from": NEW,
            "to": OLD,
            "reason": None,
        },
    ]
    _, out, _ = run(stable_code(layout), *STATUS, host=offline())
    assert section(out, "Stable install:")[-1].startswith(
        f"  last update   rolled back {NEW} -> {OLD}, "
    )


def no_record(layout: Layout) -> None:
    layout.installed_agent.unlink()


def no_target_reads(layout: Layout) -> None:
    layout.spool_reads(layout.versions / OLD).unlink()


def unreadable_agent_reads(layout: Layout) -> None:
    layout.spool_reads(layout.versions / NEW).write_text("not json\n")


def no_target_app(layout: Layout) -> None:
    shutil.rmtree(layout.agent_app(layout.versions / OLD))
    layout.agent_commit(layout.versions / OLD).unlink()


@pytest.mark.parametrize(
    ("break_it", "problem"),
    [
        (
            no_record,
            "could not tell which build the installed capture agent is; it was left as it is",
        ),
        (
            no_target_reads,
            f"could not tell which record kinds {OLD} reads; the capture agent was left as it is",
        ),
        (
            unreadable_agent_reads,
            f"could not tell which record kinds the capture agent from {NEW} writes; it was left"
            " as it is",
        ),
        (
            no_target_app,
            f"could not move the capture agent back: {OLD} does not read its heartbeat records, but"
            f" {OLD} carries no agent app; it was left as it is",
        ),
    ],
    ids=[
        "installed agent unknown",
        "target reads unknown",
        "agent writes unknown",
        "no target app",
    ],
)
def test_rollback_that_cannot_tell_or_has_no_app_warns_and_leaves_the_agent(
    run: RunCli, live: Path, checkout: Path, break_it: object, problem: str
) -> None:
    layout = updated_with_newer_agent(run, live, checkout)
    break_it(layout)  # type: ignore[operator]
    host = offline()

    code, out, err = run(stable_code(layout), "rollback", host=host)

    assert code == 0, err
    assert out[1:] == [
        f"Rolled back to version {OLD} from {NEW}",
        f"  previous      {NEW} (rollback again returns to it)",
        "  agent         not moved",
        "  backend       restarted",
        f"  warning: {problem}",
    ]
    assert agent_calls(host) == []
    assert agent_built_from(layout.capture_agent_app) == NEWER
    assert layout.current.resolve().name == OLD
    assert host.jobs[BACKEND.label].loaded
    assert [line["action"] for line in log_lines(layout)] == ["updated", "rolled back"]


def test_an_agent_that_does_not_start_after_the_move_is_a_problem_and_rollback_goes_on(
    run: RunCli, live: Path, checkout: Path
) -> None:
    layout = updated_with_newer_agent(run, live, checkout)
    host = offline()
    host.agent_register_error = "the capture agent is registered but did not start"

    code, out, err = run(stable_code(layout), "rollback", host=host)

    assert code == 0, err
    assert out[1:] == [
        f"Rolled back to version {OLD} from {NEW}",
        f"  previous      {NEW} (rollback again returns to it)",
        "  agent         not moved",
        "  backend       restarted",
        f"  warning: could not move the capture agent back to {OLD}'s build: the capture agent is"
        " registered but did not start; the next update deploys it again",
    ]
    assert not layout.installed_agent.exists()
    assert layout.current.resolve().name == OLD
    assert host.jobs[BACKEND.label].loaded
    assert [line["action"] for line in log_lines(layout)] == ["updated", "rolled back"]


def test_an_agent_already_on_the_previous_versions_build_stays(
    run: RunCli, live: Path, checkout: Path
) -> None:
    layout = updated_with_newer_agent(run, live, checkout)
    shutil.rmtree(layout.capture_agent_app)
    lay_out_agent(layout.capture_agent_app, OLDER)
    record_installed_agent(layout, OLDER, INSTALLED_AT)
    host = offline()

    code, out, err = run(stable_code(layout), "rollback", host=host)

    assert code == 0, err
    assert out[3] == f"  agent         not moved ({OLD} carries the same build)"
    assert agent_calls(host) == []


def test_status_skips_update_log_lines_whose_action_it_does_not_know(
    run: RunCli, live: Path, checkout: Path
) -> None:
    layout = install_older(run, live, checkout)
    known = {"at": "2026-11-20T17:22:03+00:00", "action": "rolled back", "from": NEW, "to": OLD}
    unknown = {
        "at": "2026-11-21T09:00:00+00:00",
        "action": "agent wandered",
        "from": "x",
        "to": "y",
    }
    layout.update_log.write_text(f"{json.dumps(known)}\n{json.dumps(unknown)}\n")

    _, out, _ = run(stable_code(layout), *STATUS, host=FakeHost())

    assert section(out, "Stable install:")[-1].startswith(
        f"  last update   rolled back {NEW} -> {OLD}, "
    )
