from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from computer_history.stable.capture_agent import (
    AgentRecord,
    agent_record,
    record_installed_agent,
)
from computer_history.stable.layout import Layout
from computer_history.stable.updates.phases import (
    ROLLBACK_PHASES,
    UPDATE_PHASES,
    RollbackPhase,
    UpdatePhase,
    rollback_phases,
    update_phases,
)
from computer_history.stable.versions import VersionState, stepped, version_state
from computer_history.store import INSTALL_MARKER_NAME
from computer_history.transitions import IllegalTransition
from computer_history.watchdog.alerts import AlertState, Notice, alert_state, record_notice
from computer_history.watchdog.checks import Check
from computer_history.watchdog.state import (
    WatchdogState,
    read_watchdog_state,
    write_watchdog_state,
)
from tests.fake_host import FakeHost

NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
COMMIT = "a" * 40
OTHER = "b" * 40
SWITCHING = (
    UpdatePhase.HOLD_PLACED,
    UpdatePhase.PREVIOUS_FLIPPED,
    UpdatePhase.CURRENT_FLIPPED,
    UpdatePhase.BACKEND_LOADED,
)


@pytest.fixture
def layout(tmp_path: Path) -> Layout:
    return Layout(tmp_path / "live", tmp_path / "home")


def test_an_update_runs_its_phases_in_order_to_finished() -> None:
    phases = update_phases()
    for phase in (
        UpdatePhase.BUILT,
        UpdatePhase.AGENT_PLACED,
        UpdatePhase.BACKEND_STOPPED,
        UpdatePhase.BACKED_UP,
        UpdatePhase.HOLD_PLACED,
        UpdatePhase.PREVIOUS_FLIPPED,
        UpdatePhase.CURRENT_FLIPPED,
        UpdatePhase.BACKEND_LOADED,
        UpdatePhase.FIRST_CYCLE_OK,
        UpdatePhase.AGENT_SWAPPED,
        UpdatePhase.AGENT_VERIFIED,
        UpdatePhase.FINISHED,
    ):
        phases.advance(phase)
    assert phases.phase is UpdatePhase.FINISHED


@pytest.mark.parametrize("phase", list(UpdatePhase), ids=lambda phase: phase.name)
def test_an_update_falls_back_only_while_it_switches(phase: UpdatePhase) -> None:
    if phase in SWITCHING:
        assert UPDATE_PHASES.move(phase, UpdatePhase.FALLING_BACK) is UpdatePhase.FALLING_BACK
    else:
        with pytest.raises(IllegalTransition):
            UPDATE_PHASES.move(phase, UpdatePhase.FALLING_BACK)


def test_a_refused_phase_leaves_the_run_where_it_was() -> None:
    phases = update_phases()
    with pytest.raises(IllegalTransition, match="update: CHECKED -> FINISHED"):
        phases.advance(UpdatePhase.FINISHED)
    assert phases.phase is UpdatePhase.CHECKED


def test_a_rollback_is_undone_only_between_its_two_flips() -> None:
    phases = rollback_phases()
    phases.advance(RollbackPhase.CURRENT_FLIPPED)
    phases.advance(RollbackPhase.UNDONE)
    with pytest.raises(IllegalTransition):
        ROLLBACK_PHASES.move(RollbackPhase.PREVIOUS_FLIPPED, RollbackPhase.UNDONE)


def test_a_version_folder_state_is_read_from_disk_at_each_stage(layout: Layout) -> None:
    folder = layout.versions / COMMIT[:12]
    assert version_state(layout, folder) is VersionState.ABSENT
    folder.mkdir(parents=True)
    assert version_state(layout, folder) is VersionState.PARTIAL
    (folder / INSTALL_MARKER_NAME).write_text("")
    assert version_state(layout, folder) is VersionState.MARKED_NO_AGENT
    layout.agent_app(folder).mkdir()
    assert version_state(layout, folder) is VersionState.MARKED_NO_AGENT
    layout.agent_commit(folder).write_text(f"{COMMIT}\n", encoding="utf-8")
    assert version_state(layout, folder) is VersionState.COMPLETE


def test_a_step_that_completes_a_folder_never_marked_is_refused(layout: Layout) -> None:
    folder = layout.versions / COMMIT[:12]
    folder.mkdir(parents=True)
    (folder / INSTALL_MARKER_NAME).write_text("")
    layout.agent_app(folder).mkdir()
    layout.agent_commit(folder).write_text(f"{COMMIT}\n", encoding="utf-8")
    with pytest.raises(IllegalTransition, match="ABSENT -> COMPLETE"):
        stepped(layout, folder, VersionState.ABSENT)


def test_the_installed_agent_record_is_none_unknown_matching_or_stale(layout: Layout) -> None:
    host = FakeHost(agent_trees={COMMIT: "tree-a", OTHER: "tree-b"})
    assert agent_record(host, layout, COMMIT) == (AgentRecord.NONE, None)
    layout.capture_agent_app.mkdir(parents=True)
    assert agent_record(host, layout, COMMIT) == (AgentRecord.UNKNOWN, None)
    layout.live.mkdir()
    record_installed_agent(layout, OTHER, NOW)
    assert agent_record(host, layout, OTHER)[0] is AgentRecord.MATCHING
    assert agent_record(host, layout, COMMIT)[0] is AgentRecord.STALE
    host.agent_trees[COMMIT] = "tree-b"
    assert agent_record(host, layout, COMMIT)[0] is AgentRecord.MATCHING


def test_a_notified_problem_stays_open_until_its_clear_is_recorded() -> None:
    notified: dict[Check, datetime] = {}
    check = Check.CAPTURE_AGENT
    record_notice(notified, Notice(check, False, "silent"), NOW)
    assert alert_state(notified, check) is AlertState.OPEN_NOTIFIED
    record_notice(notified, Notice(check, True, "recording again"), NOW)
    assert alert_state(notified, check) is AlertState.CLOSED
    with pytest.raises(IllegalTransition, match="CLOSED -> CLOSED"):
        record_notice(notified, Notice(check, True, "recording again"), NOW)


def test_watchdog_state_loads_with_or_without_the_old_open_list(tmp_path: Path) -> None:
    path = tmp_path / "watchdog.json"
    state = WatchdogState(ran_at=NOW, notified={Check.BACKEND: NOW})
    write_watchdog_state(path, state)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["open"] == [Check.BACKEND.value]
    assert read_watchdog_state(path) == state
    del saved["open"]
    path.write_text(json.dumps(saved), encoding="utf-8")
    assert read_watchdog_state(path) == state
