"""What a source adapter implements for the ingest runner to drive it."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from computer_history.store import Observation

__all__ = ["HistorySource", "Pull", "Source", "SourceUnavailable"]


class SourceUnavailable(RuntimeError):
    """The source could not be read right now; the runner retries it later."""


@dataclass(frozen=True)
class Pull:
    """The settled observations one pull read, and where the stream's progress now stands.

    A position of None leaves the stream's stored progress as it is.
    """

    observations: tuple[Observation, ...]
    held_back: int
    position: str | None
    settled_until: datetime | None


class Source(Protocol):
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
