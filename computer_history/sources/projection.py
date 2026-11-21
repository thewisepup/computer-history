from __future__ import annotations

import logging
import sqlite3
import time
from collections.abc import Callable, Iterable

from computer_history.logs import Outcome
from computer_history.sources.activitywatch.adapter import ActivityWatch
from computer_history.sources.capture_spool.adapter import CaptureSpool
from computer_history.sources.contract import Projecting, StreamProjector
from computer_history.store import (
    Projector,
    RebuildAborted,
    RebuildResult,
    Signal,
    UnclaimedSource,
    rebuild_signals,
)

__all__ = ["KNOWN_SOURCES", "projector_for", "reproject_signals"]

KNOWN_SOURCES: tuple[type[Projecting], ...] = (ActivityWatch, CaptureSpool)

log = logging.getLogger(__name__)


def projector_for(sources: Iterable[Projecting | type[Projecting]]) -> Projector:
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
    sources: Iterable[Projecting | type[Projecting]] = KNOWN_SOURCES,
    monotonic: Callable[[], float] = time.monotonic,
) -> RebuildResult:
    """Rebuild every signal from the stored observations through the known adapters' projectors.

    The run logs its start and, however it ends, one record with its outcome and counts.
    """
    sources = list(sources)
    log.info("rebuild started", extra={"allow_shrink": allow_shrink})
    began = monotonic()
    outcome, result, error = Outcome.CRASHED, None, None
    try:
        result = rebuild_signals(
            conn, projector_for(sources), claimed=_routes(sources).keys(), allow_shrink=allow_shrink
        )
        outcome = Outcome.OK
        return result
    except RebuildAborted as exc:
        outcome, error = Outcome.ABORTED, exc
        raise
    except sqlite3.Error as exc:
        outcome, error = Outcome.FAILED, exc
        raise
    except KeyboardInterrupt:
        outcome = Outcome.INTERRUPTED
        raise
    finally:
        fields: dict[str, object] = {
            "outcome": outcome.value,
            "duration_ms": round((monotonic() - began) * 1000),
        }
        if result is not None:
            fields.update(
                signals_before=result.signals_before,
                signals_after=result.signals_after,
                failed=result.skipped,
            )
        if isinstance(error, RebuildAborted):
            fields.update(error=str(error), failed=error.failed, shrink=error.shrink)
        if outcome is Outcome.OK:
            log.info("rebuild finished", extra=fields)
        else:
            log.error(
                "rebuild finished",
                extra=fields,
                exc_info=error if outcome is Outcome.FAILED else None,
            )


def _routes(sources: Iterable[Projecting | type[Projecting]]) -> dict[str, StreamProjector]:
    routes: dict[str, StreamProjector] = {}
    for source in sources:
        for stream, project in source.projectors.items():
            if routes.setdefault(stream, project) != project:
                raise ValueError(f"stream {stream!r} is fed by more than one source")
    return routes
