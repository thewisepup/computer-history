from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Generic, TypeVar

S = TypeVar("S", bound=Enum)


class IllegalTransition(RuntimeError):
    """A state change that the machine's table of allowed changes does not list."""

    def __init__(self, machine: str, current: Enum, target: Enum) -> None:
        super().__init__(f"{machine}: {current.name} -> {target.name} is not allowed")
        self.machine = machine
        self.current = current
        self.target = target


class TransitionTable(Generic[S]):
    """The states each state of one machine may move to, checked on every change."""

    def __init__(self, machine: str, allowed: Mapping[S, frozenset[S]]) -> None:
        states = {state for state in allowed} | {t for targets in allowed.values() for t in targets}
        missing = [state.name for state in type(next(iter(states))) if state not in allowed]
        if missing:
            raise ValueError(f"{machine}: no entry for {missing}")
        self.machine = machine
        self._allowed = dict(allowed)

    def move(self, current: S, target: S) -> S:
        """Return target when the table allows the move, else raise IllegalTransition."""
        if target not in self._allowed[current]:
            raise IllegalTransition(self.machine, current, target)
        return target
