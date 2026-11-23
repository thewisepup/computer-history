from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from computer_history.sources import (
    IngestHealth,
    SourceUnavailable,
    active_spans,
    capture_liveness,
    read_health,
)
from computer_history.sources.activitywatch import AWApi, discover_sources, watcher_ends
from computer_history.sources.capture_spool import Span
from computer_history.watchdog.checks import (
    Check,
    Finding,
    Reason,
    Verdict,
    judge_activitywatch,
    judge_backend,
    judge_capture_agent,
)


@dataclass(frozen=True)
class Assessment:
    """The capture agent's, ActivityWatch's and the backend's findings, and what they rest on."""

    capture_agent: Finding
    activitywatch: Finding
    backend: Finding
    watched_since: datetime
    unreachable_since: datetime | None
    health: IngestHealth | None = None
    health_error: str | None = None
    aw_sources: tuple[str, ...] | None = None
    buckets: Mapping[str, Any] | None = None

    @property
    def findings(self) -> tuple[Finding, ...]:
        return (self.capture_agent, self.activitywatch, self.backend)


def assess(
    conn: sqlite3.Connection | None,
    client: AWApi,
    *,
    spool: Path,
    health_file: Path,
    silent_after: Mapping[Check, timedelta],
    watched_since: datetime,
    unreachable_since: datetime | None,
    now: datetime,
    hostname: str,
) -> Assessment:
    """Judge the capture agent, ActivityWatch and the backend as of now, counting silence from
    watched_since."""
    try:
        buckets = client.get_buckets()
        ends, aw_error = watcher_ends(client, buckets, hostname=hostname), None
        aw_sources = tuple(source.name for source in discover_sources(buckets))
    except SourceUnavailable as exc:
        buckets, ends, aw_error, aw_sources = None, None, str(exc), None
    since = unreachable_since or now

    reach = max(silent_after.values())
    capture_after = silent_after[Check.CAPTURE_AGENT]
    try:
        active, store_error = active_spans(conn, client, buckets, now - reach, now), None
        found = capture_liveness(
            conn,
            spool,
            now=now,
            active=_since(active, now - capture_after),
            watched_since=watched_since,
            alive_within=capture_after,
        )
        capture = judge_capture_agent(found, now=now, silent_after=capture_after)
    except sqlite3.Error as exc:
        active, store_error = [], f"database read failed: {exc}"
        capture = Finding(
            Check.CAPTURE_AGENT, Verdict.UNKNOWN, Reason.UNREADABLE, detail=store_error
        )
    try:
        health, health_error = read_health(health_file), None
    except (OSError, ValueError) as exc:
        health, health_error = None, str(exc)
    if health_error is not None:
        backend = Finding(Check.BACKEND, Verdict.UNKNOWN, Reason.UNREADABLE, detail=health_error)
    else:
        backend = judge_backend(
            health,
            now=now,
            active=_since(active, now - silent_after[Check.BACKEND]),
            watched_since=watched_since,
            silent_after=silent_after[Check.BACKEND],
        )
        if store_error is not None and backend.verdict is not Verdict.OK:
            backend = replace(
                backend, verdict=Verdict.UNKNOWN, reason=Reason.UNREADABLE, detail=store_error
            )
    activitywatch = judge_activitywatch(
        ends,
        unreachable_since=since,
        error=aw_error,
        now=now,
        watched_since=watched_since,
        silent_after=silent_after[Check.ACTIVITYWATCH],
    )
    return Assessment(
        capture,
        activitywatch,
        backend,
        watched_since,
        None if ends is not None else since,
        health,
        health_error,
        aw_sources,
        buckets,
    )


def _since(active: list[Span], start: datetime) -> list[Span]:
    return [(max(a, start), b) for a, b in active if b > start]
