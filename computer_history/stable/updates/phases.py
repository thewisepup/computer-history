from __future__ import annotations

from enum import Enum, auto
from typing import Generic

from computer_history.transitions import S, TransitionTable


class UpdatePhase(Enum):
    CHECKED = auto()
    BUILT = auto()
    AGENT_PLACED = auto()
    BACKEND_STOPPED = auto()
    BACKED_UP = auto()
    HOLD_PLACED = auto()
    PREVIOUS_FLIPPED = auto()
    CURRENT_FLIPPED = auto()
    BACKEND_LOADED = auto()
    FIRST_CYCLE_OK = auto()
    AGENT_SWAPPED = auto()
    AGENT_VERIFIED = auto()
    FINISHED = auto()
    FALLING_BACK = auto()
    FELL_BACK = auto()


class RollbackPhase(Enum):
    CHECKED = auto()
    CURRENT_FLIPPED = auto()
    PREVIOUS_FLIPPED = auto()
    BACKEND_LOADED = auto()
    FINISHED = auto()
    UNDONE = auto()


UPDATE_PHASES = TransitionTable(
    "update",
    {
        UpdatePhase.CHECKED: frozenset({UpdatePhase.BUILT}),
        UpdatePhase.BUILT: frozenset({UpdatePhase.AGENT_PLACED, UpdatePhase.BACKEND_STOPPED}),
        UpdatePhase.AGENT_PLACED: frozenset({UpdatePhase.BACKEND_STOPPED}),
        UpdatePhase.BACKEND_STOPPED: frozenset({UpdatePhase.BACKED_UP, UpdatePhase.HOLD_PLACED}),
        UpdatePhase.BACKED_UP: frozenset({UpdatePhase.HOLD_PLACED}),
        UpdatePhase.HOLD_PLACED: frozenset(
            {UpdatePhase.PREVIOUS_FLIPPED, UpdatePhase.FALLING_BACK}
        ),
        UpdatePhase.PREVIOUS_FLIPPED: frozenset(
            {UpdatePhase.CURRENT_FLIPPED, UpdatePhase.FALLING_BACK}
        ),
        UpdatePhase.CURRENT_FLIPPED: frozenset(
            {UpdatePhase.BACKEND_LOADED, UpdatePhase.FALLING_BACK}
        ),
        UpdatePhase.BACKEND_LOADED: frozenset(
            {UpdatePhase.FIRST_CYCLE_OK, UpdatePhase.FALLING_BACK}
        ),
        UpdatePhase.FIRST_CYCLE_OK: frozenset({UpdatePhase.AGENT_SWAPPED, UpdatePhase.FINISHED}),
        UpdatePhase.AGENT_SWAPPED: frozenset({UpdatePhase.AGENT_VERIFIED, UpdatePhase.FINISHED}),
        UpdatePhase.AGENT_VERIFIED: frozenset({UpdatePhase.FINISHED}),
        UpdatePhase.FINISHED: frozenset(),
        UpdatePhase.FALLING_BACK: frozenset({UpdatePhase.FELL_BACK}),
        UpdatePhase.FELL_BACK: frozenset(),
    },
)

ROLLBACK_PHASES = TransitionTable(
    "rollback",
    {
        RollbackPhase.CHECKED: frozenset({RollbackPhase.CURRENT_FLIPPED}),
        RollbackPhase.CURRENT_FLIPPED: frozenset(
            {RollbackPhase.PREVIOUS_FLIPPED, RollbackPhase.UNDONE}
        ),
        RollbackPhase.PREVIOUS_FLIPPED: frozenset({RollbackPhase.BACKEND_LOADED}),
        RollbackPhase.BACKEND_LOADED: frozenset({RollbackPhase.FINISHED}),
        RollbackPhase.FINISHED: frozenset(),
        RollbackPhase.UNDONE: frozenset(),
    },
)


class Progress(Generic[S]):
    """The phase one update or rollback has reached, moved only along its table."""

    def __init__(self, table: TransitionTable[S], start: S) -> None:
        self._table = table
        self.phase = start

    def advance(self, target: S) -> None:
        self.phase = self._table.move(self.phase, target)


def update_progress() -> Progress[UpdatePhase]:
    return Progress(UPDATE_PHASES, UpdatePhase.CHECKED)


def rollback_progress() -> Progress[RollbackPhase]:
    return Progress(ROLLBACK_PHASES, RollbackPhase.CHECKED)
