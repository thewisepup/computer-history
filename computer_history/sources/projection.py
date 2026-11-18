"""Route each observation to the projector of the source adapter that claims its stream."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from computer_history.sources.activitywatch.adapter import ActivityWatch
from computer_history.sources.contract import Projecting, StreamProjector
from computer_history.store import (
    Projector,
    RebuildResult,
    Signal,
    UnclaimedSource,
    rebuild_signals,
)

__all__ = ["KNOWN_SOURCES", "projector_for", "reproject_signals"]

KNOWN_SOURCES: tuple[Projecting, ...] = (ActivityWatch,)


def projector_for(sources: Iterable[Projecting]) -> Projector:
    """One projector over every stream the sources claim, raising UnclaimedSource for any other.

    Two sources claiming one stream with different projectors are refused.
    """
    routes = _routes(sources)

    def project(source: str, payload: str) -> Signal | None:
        route = routes.get(source)
        if route is None:
            raise UnclaimedSource(source)
        return route(payload)

    return project


def reproject_signals(
    conn: sqlite3.Connection,
    *,
    allow_shrink: bool = False,
    sources: Iterable[Projecting] = KNOWN_SOURCES,
) -> RebuildResult:
    """Rebuild every signal from the stored observations through the known adapters' projectors."""
    sources = list(sources)
    return rebuild_signals(
        conn, projector_for(sources), claimed=_routes(sources).keys(), allow_shrink=allow_shrink
    )


def _routes(sources: Iterable[Projecting]) -> dict[str, StreamProjector]:
    routes: dict[str, StreamProjector] = {}
    for source in sources:
        for stream, project in source.projectors.items():
            if routes.setdefault(stream, project) != project:
                raise ValueError(f"stream {stream!r} is fed by more than one source")
    return routes
