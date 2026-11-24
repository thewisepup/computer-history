from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

import pytest

from computer_history.sources.capture_spool.adapter import FILE_STATES, FileState
from computer_history.sources.ingest_health import (
    STREAK_STATES,
    IngestHealth,
    StreakState,
    read_health,
    streak_state,
)
from computer_history.sources.progress_moves import (
    ProgressMove,
    ProgressRule,
    next_position,
    progress_move,
)
from computer_history.transitions import IllegalTransition, TransitionTable

F = FileState
S = StreakState

TABLES: list[tuple[TransitionTable[Any], type[Enum], dict[Any, set[Any]]]] = [
    (
        FILE_STATES,
        FileState,
        {
            F.LISTED: {F.STORED_BY_SOME, F.STORED_BY_ALL, F.UNREADABLE, F.UNREADABLE_BY_ALL},
            F.STORED_BY_SOME: {F.STORED_BY_SOME, F.STORED_BY_ALL},
            F.UNREADABLE: {F.UNREADABLE, F.UNREADABLE_BY_ALL, F.STORED_BY_SOME, F.STORED_BY_ALL},
            F.STORED_BY_ALL: {F.REMOVED, F.KEPT_FOR_HOLD, F.STUCK, F.LISTED},
            F.UNREADABLE_BY_ALL: {F.REMOVED, F.KEPT_FOR_HOLD, F.STUCK, F.LISTED},
            F.REMOVED: {F.LISTED},
            F.KEPT_FOR_HOLD: {F.LISTED},
            F.STUCK: set(),
        },
    ),
    (
        STREAK_STATES,
        StreakState,
        {
            S.HEALTHY: {S.HEALTHY, S.FAILING},
            S.FAILING: {S.FAILING, S.ALERTED, S.HEALTHY},
            S.ALERTED: {S.ALERTED, S.HEALTHY},
        },
    ),
]


@pytest.mark.parametrize(
    ("table", "states", "allowed"), TABLES, ids=[table.machine for table, _, _ in TABLES]
)
def test_each_table_allows_exactly_its_listed_moves(
    table: TransitionTable[Any], states: type[Enum], allowed: dict[Any, set[Any]]
) -> None:
    for current in states:
        for target in states:
            if target in allowed[current]:
                assert table.move(current, target) is target
            else:
                with pytest.raises(IllegalTransition):
                    table.move(current, target)


def test_a_stuck_spool_file_never_moves_again() -> None:
    with pytest.raises(IllegalTransition, match="spool file: STUCK -> LISTED is not allowed"):
        FILE_STATES.move(FileState.STUCK, FileState.LISTED)


def test_an_alerted_streak_cannot_fall_back_to_failing_without_alerting() -> None:
    with pytest.raises(IllegalTransition, match="failure streak: ALERTED -> FAILING"):
        STREAK_STATES.move(StreakState.ALERTED, StreakState.FAILING)


NOW = datetime(2026, 11, 24, 12, tzinfo=UTC)
EARLY = "2026-11-24T10:00:00.000000Z"
LATE = "2026-11-24T11:00:00.000000Z"
FUTURE = "2026-11-25T12:00:00.000000Z"


@pytest.mark.parametrize(
    ("stored", "new", "move"),
    [
        (None, EARLY, ProgressMove.FIRST),
        (EARLY, LATE, ProgressMove.FORWARD),
        (LATE, LATE, ProgressMove.UNCHANGED),
        (LATE, EARLY, ProgressMove.BACKWARD),
    ],
)
def test_a_progress_move_is_classified_against_the_stored_position(
    stored: str | None, new: str, move: ProgressMove
) -> None:
    assert progress_move(stored, new) is move


@pytest.mark.parametrize(
    ("stored", "new", "moved_to"),
    [
        (None, EARLY, EARLY),
        (EARLY, LATE, LATE),
        (LATE, LATE, None),
        (LATE, EARLY, None),
        (FUTURE, EARLY, EARLY),
        (EARLY, None, None),
    ],
)
def test_the_spool_moves_progress_back_only_from_a_position_past_now(
    stored: str | None, new: str | None, moved_to: str | None
) -> None:
    assert next_position(ProgressRule.FORWARD_ONLY, stored, new, now=NOW) == moved_to


@pytest.mark.parametrize("stored", [None, EARLY, LATE])
def test_activitywatch_moves_progress_back_to_an_event_held_back(stored: str | None) -> None:
    assert next_position(ProgressRule.SETTLED_FRONTIER, stored, EARLY, now=NOW) == EARLY


def test_the_streak_state_follows_failures_and_alerts() -> None:
    assert streak_state(None) is StreakState.HEALTHY
    assert streak_state(IngestHealth(NOW)) is StreakState.HEALTHY
    assert streak_state(IngestHealth(NOW, 2, NOW)) is StreakState.FAILING
    assert streak_state(IngestHealth(NOW, 5, NOW, alerted_at=NOW)) is StreakState.ALERTED


@pytest.mark.parametrize("field", ["failing_since", "alerted_at"])
def test_a_health_file_with_a_streak_but_no_failures_is_refused(tmp_path: Path, field: str) -> None:
    path = tmp_path / "ingest-health.json"
    since = (NOW - timedelta(minutes=5)).isoformat()
    doc = {"cycle_at": NOW.isoformat(), "consecutive_failures": 0, field: since}
    path.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ValueError, match="a failure streak with no failures"):
        read_health(path)
