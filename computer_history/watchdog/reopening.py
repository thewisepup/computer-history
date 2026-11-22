from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from computer_history.host import Host, HostError

REOPEN_LIMIT = 3
REOPEN_WINDOW = timedelta(hours=1)


@dataclass(frozen=True)
class Reopening:
    """The reopens inside the window after this run, and what this run did about a down app."""

    reopens: tuple[datetime, ...]
    reopened: bool = False
    refused: bool = False
    error: str | None = None


def recent_reopens(reopened: Iterable[datetime], now: datetime) -> tuple[datetime, ...]:
    """Keep the reopens of ActivityWatch that fall inside the window the limit counts."""
    return tuple(at for at in reopened if now - at < REOPEN_WINDOW)


def reopen_if_closed(host: Host, reopened: Iterable[datetime], now: datetime) -> Reopening:
    """Open ActivityWatch when its app isn't running, unless the hourly limit is reached."""
    reopens = recent_reopens(reopened, now)
    try:
        if host.activitywatch_running():
            return Reopening(reopens)
        if len(reopens) >= REOPEN_LIMIT:
            return Reopening(reopens, refused=True)
        host.open_activitywatch()
    except HostError as exc:
        return Reopening(reopens, error=str(exc))
    return Reopening((*reopens, now), reopened=True)
