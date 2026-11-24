from __future__ import annotations

from enum import Enum, auto

import pytest

from computer_history.transitions import IllegalTransition, TransitionTable


class Light(Enum):
    OFF = auto()
    ON = auto()
    BROKEN = auto()


TABLE = TransitionTable(
    "light",
    {
        Light.OFF: frozenset({Light.ON, Light.BROKEN}),
        Light.ON: frozenset({Light.OFF, Light.BROKEN}),
        Light.BROKEN: frozenset(),
    },
)


def test_an_allowed_move_returns_the_target() -> None:
    assert TABLE.move(Light.OFF, Light.ON) is Light.ON


def test_a_move_the_table_does_not_list_raises_and_names_both_states() -> None:
    with pytest.raises(IllegalTransition, match="light: BROKEN -> ON is not allowed"):
        TABLE.move(Light.BROKEN, Light.ON)


def test_a_table_missing_a_state_is_refused_when_built() -> None:
    with pytest.raises(ValueError, match="BROKEN"):
        TransitionTable("light", {Light.OFF: frozenset({Light.ON}), Light.ON: frozenset()})
