from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import assert_never

from computer_history.transitions import TransitionTable

SPOOL_HOLD_NAME = "spool-deletion-held"


class HoldState(Enum):
    ABSENT = auto()
    PLACED = auto()


HOLD_STATES = TransitionTable(
    "spool hold",
    {
        HoldState.ABSENT: frozenset({HoldState.ABSENT, HoldState.PLACED}),
        HoldState.PLACED: frozenset({HoldState.PLACED, HoldState.ABSENT}),
    },
)


def spool_hold_path(db_path: Path) -> Path:
    """The file beside the database telling ingest to keep spool files until a cycle is ok."""
    return db_path.parent / SPOOL_HOLD_NAME


@dataclass(frozen=True)
class SpoolHold:
    """The hold on spool deletion that update places before restarting the backend."""

    path: Path

    @classmethod
    def beside(cls, db_path: Path) -> SpoolHold:
        return cls(spool_hold_path(db_path))

    @property
    def state(self) -> HoldState:
        return HoldState.PLACED if self.path.exists() else HoldState.ABSENT

    @property
    def active(self) -> bool:
        return self.state is HoldState.PLACED

    def place(self) -> None:
        self._move(HoldState.PLACED)

    def release(self) -> None:
        self._move(HoldState.ABSENT)

    def _move(self, target: HoldState) -> None:
        HOLD_STATES.move(self.state, target)
        match target:
            case HoldState.PLACED:
                self.path.write_text("")
            case HoldState.ABSENT:
                self.path.unlink(missing_ok=True)
            case _:
                assert_never(target)
