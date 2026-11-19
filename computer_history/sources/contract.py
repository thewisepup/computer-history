from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from computer_history.store import Observation, Signal

__all__ = [
    "HistorySource",
    "Projecting",
    "Pull",
    "Source",
    "SourceUnavailable",
    "StreamProjector",
]

StreamProjector = Callable[[str], Signal | None]


class SourceUnavailable(RuntimeError):
    """The source could not be read right now; the runner retries it later."""


@dataclass(frozen=True)
class Pull:
    """The settled observations one pull read, and where the stream's progress now stands.

    A position of None leaves the stream's stored progress as it is, and more asks to pull again.
    """

    observations: tuple[Observation, ...]
    held_back: int
    position: str | None
    settled_until: datetime | None
    rejected: int = 0
    more: bool = False
    after_commit: Callable[[], None] | None = field(default=None, compare=False)


class Projecting(Protocol):
    """Maps each stream an adapter can feed to the function that projects its stored payloads."""

    projectors: Mapping[str, StreamProjector]


class Source(Projecting, Protocol):
    """A source of observations, split into named streams, each with its own progress."""

    def streams(self) -> Sequence[str]:
        """The streams this source feeds right now."""
        ...

    def pull_after(self, stream: str, position: str | None, *, now: datetime) -> Pull:
        """The stream's settled observations after its stored position, or all of them."""
        ...


class HistorySource(Source, Protocol):
    """A source whose existing history can be planned and read back by time range."""

    def parts(self, stream: str) -> tuple[str, ...]:
        """The feeds the stream is read from."""
        ...

    def history_start(self, stream: str) -> datetime | None:
        """Where the stream's history begins, if the source can tell."""
        ...

    def history_before(
        self, stream: str, start: datetime
    ) -> tuple[tuple[str, datetime | None], ...]:
        """Each part with history before the start, and when its newest such event began."""
        ...

    def pull_range(self, stream: str, start: datetime, end: datetime, *, now: datetime) -> Pull:
        """The stream's settled observations starting in the range."""
        ...
