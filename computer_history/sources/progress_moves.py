"""Whether a stream's progress may move from its stored position to the one a pull reached."""

from __future__ import annotations

from datetime import datetime
from enum import Enum, auto
from typing import assert_never

from computer_history.store import utc_iso

__all__ = ["ProgressMove", "ProgressRule", "next_position", "progress_move"]


class ProgressMove(Enum):
    FIRST = auto()  # the stream has no stored position yet
    FORWARD = auto()
    UNCHANGED = auto()
    BACKWARD = auto()


class ProgressRule(Enum):
    FORWARD_ONLY = auto()  # the capture spool: back only from a stored position past now
    SETTLED_FRONTIER = auto()  # ActivityWatch: back to the start of an event held back


def progress_move(stored: str | None, new: str) -> ProgressMove:
    """How the new position stands against the stored one."""
    if stored is None:
        return ProgressMove.FIRST
    if new > stored:
        return ProgressMove.FORWARD
    if new == stored:
        return ProgressMove.UNCHANGED
    return ProgressMove.BACKWARD


def next_position(
    rule: ProgressRule, stored: str | None, new: str | None, *, now: datetime
) -> str | None:
    """The position the stream's progress moves to under the rule, or None to leave it."""
    if new is None:
        return None
    move = progress_move(stored, new)
    match rule:
        case ProgressRule.SETTLED_FRONTIER:
            return new
        case ProgressRule.FORWARD_ONLY:
            match move:
                case ProgressMove.FIRST | ProgressMove.FORWARD:
                    return new
                case ProgressMove.UNCHANGED | ProgressMove.BACKWARD:
                    return new if stored is not None and stored > utc_iso(now) else None
                case _:
                    assert_never(move)
        case _:
            assert_never(rule)
