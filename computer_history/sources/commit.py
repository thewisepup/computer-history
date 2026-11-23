from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from computer_history.sources.contract import Pull, SourceUnavailable
from computer_history.store import ProgressUpdate, Projector, UnclaimedSource, insert_observations

__all__ = [
    "Committed",
    "FailureKind",
    "StrayObservation",
    "StreamFailure",
    "commit_pull",
    "failure_of",
]


class StrayObservation(ValueError):
    """A pull returned an observation from a stream other than the one pulled."""


@dataclass(frozen=True)
class Committed:
    """What one commit wrote, and whether it carried a progress update and moved the progress."""

    inserted: int
    skipped: int
    progress_sent: bool
    progress_moved: bool


def commit_pull(
    conn: sqlite3.Connection,
    stream: str,
    pulled: Pull,
    *,
    project: Projector,
    now: datetime,
    progress_from: Pull | None = None,
    only_if_none: bool = False,
) -> Committed:
    """Write the pull's observations, signals and progress at once, then run its after-commit step.

    A progress_from without a position sends no progress update.
    """
    for observation in pulled.observations:
        if observation.source != stream:
            raise StrayObservation(
                f"a pull of {stream!r} returned an observation from {observation.source!r}"
            )
    update = None
    if progress_from is not None and progress_from.position is not None:
        update = ProgressUpdate(
            stream,
            progress_from.position,
            settled_until=progress_from.settled_until,
            only_if_none=only_if_none,
        )
    written = insert_observations(
        conn, pulled.observations, project=project, progress=update, now=now
    )
    if pulled.after_commit is not None:
        pulled.after_commit()
    return Committed(written.inserted, written.skipped, update is not None, written.progress_moved)


class FailureKind(Enum):
    SOURCE = "source"  # the source was unavailable
    DATABASE_BUSY = "database busy"  # an operational database error, such as a lock held elsewhere
    DATABASE = "database"  # any other database error
    ADAPTER = "adapter"  # the adapter returned observations the stream cannot take
    UNEXPECTED = "unexpected"  # any other error, such as a bug in the source


@dataclass(frozen=True)
class StreamFailure:
    """Why a run stopped early, and on which stream (None if the source failed listing them)."""

    stream: str | None
    error: str
    kind: FailureKind
    exc: BaseException | None = field(default=None, compare=False, repr=False)


def failure_of(stream: str | None, exc: Exception) -> StreamFailure:
    """The failure an error amounts to, naming an unexpected error by its type alone."""
    if isinstance(exc, SourceUnavailable):
        kind = FailureKind.SOURCE
    elif isinstance(exc, UnclaimedSource | StrayObservation):
        kind = FailureKind.ADAPTER
    elif isinstance(exc, sqlite3.OperationalError):
        kind = FailureKind.DATABASE_BUSY
    elif isinstance(exc, sqlite3.Error):
        kind = FailureKind.DATABASE
    else:
        return StreamFailure(
            stream, f"unexpected {type(exc).__name__}", FailureKind.UNEXPECTED, exc
        )
    return StreamFailure(stream, str(exc), kind, exc)
