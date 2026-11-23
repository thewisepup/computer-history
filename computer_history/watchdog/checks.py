from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from computer_history.sources import CaptureLiveness, IngestHealth
from computer_history.sources.capture_spool import Liveness, Span, liveness


class Check(Enum):
    CAPTURE_AGENT = "capture agent"
    ACTIVITYWATCH = "ActivityWatch"
    BACKEND = "backend"


class Verdict(Enum):
    OK = "ok"
    PROBLEM = "PROBLEM"
    UNKNOWN = "cannot tell"


class Reason(Enum):
    RECORDING = "recording"
    FAILING = "running, but its cycles fail (ingest alerts on that)"
    SILENT = "silent while you were active"
    AFK = "silent, but aw-afk does not show you active"
    PAUSED = "paused"
    RESUMED = "silent, but watched only since the watchdog resumed"
    NEVER_SEEN = "nothing recorded yet"
    UNREACHABLE = "unreachable"
    STALLED = "not advancing"
    NO_BUCKETS = "no AFK or window bucket for this host"
    UNREADABLE = "cannot be read"


@dataclass(frozen=True)
class Finding:
    """What one check found, when its subject was last seen working, and any detail to show."""

    check: Check
    verdict: Verdict
    reason: Reason
    last_seen: datetime | None = None
    detail: str | None = None


def judge_capture_agent(
    found: CaptureLiveness, *, now: datetime, silent_after: timedelta
) -> Finding:
    """Judge the capture agent from its newest record and how alive it looks."""
    last = found.last_record
    if last is None:
        return Finding(
            Check.CAPTURE_AGENT, Verdict.UNKNOWN, Reason.NEVER_SEEN, detail=found.spool_error
        )
    match found.alive:
        case Liveness.SILENT:
            return Finding(Check.CAPTURE_AGENT, Verdict.PROBLEM, Reason.SILENT, last)
        case Liveness.PAUSED:
            return Finding(Check.CAPTURE_AGENT, Verdict.UNKNOWN, Reason.PAUSED, last)
        case Liveness.ALIVE if now - last <= silent_after:
            return Finding(Check.CAPTURE_AGENT, Verdict.OK, Reason.RECORDING, last)
        case Liveness.ALIVE:
            return Finding(Check.CAPTURE_AGENT, Verdict.UNKNOWN, Reason.RESUMED, last)
        case Liveness.UNKNOWN:
            return Finding(Check.CAPTURE_AGENT, Verdict.UNKNOWN, Reason.AFK, last)


def judge_backend(
    health: IngestHealth | None,
    *,
    now: datetime,
    active: Iterable[Span],
    watched_since: datetime,
    silent_after: timedelta,
) -> Finding:
    """Judge the backend from its last cycle: a problem only when it has finished none for longer
    than the threshold, since a backend whose cycles fail alerts on its own failure streak."""
    last = None if health is None else health.cycle_at
    alive = _liveness(last, now, list(active), watched_since, silent_after)
    if alive is Liveness.SILENT:
        return Finding(Check.BACKEND, Verdict.PROBLEM, Reason.SILENT, last)
    if health is not None and now - health.cycle_at <= silent_after:
        if health.ok:
            return Finding(Check.BACKEND, Verdict.OK, Reason.RECORDING, health.cycle_at)
        return Finding(
            Check.BACKEND, Verdict.OK, Reason.FAILING, health.cycle_at, health.last_error
        )
    if alive is Liveness.ALIVE:
        reason = Reason.NEVER_SEEN if last is None else Reason.RESUMED
        return Finding(Check.BACKEND, Verdict.UNKNOWN, reason, last)
    return Finding(Check.BACKEND, Verdict.UNKNOWN, Reason.AFK, last)


def judge_activitywatch(
    ends: Mapping[str, datetime | None] | None,
    *,
    unreachable_since: datetime | None,
    error: str | None,
    now: datetime,
    watched_since: datetime,
    silent_after: timedelta,
) -> Finding:
    """Judge ActivityWatch unreachable, or one of its sources not advancing, past the threshold."""
    if ends is None:
        since = now if unreachable_since is None else unreachable_since
        silent = now - max(since, watched_since) >= silent_after
        verdict = Verdict.PROBLEM if silent else Verdict.UNKNOWN
        return Finding(Check.ACTIVITYWATCH, verdict, Reason.UNREACHABLE, since, error)
    if not ends:
        return Finding(Check.ACTIVITYWATCH, Verdict.UNKNOWN, Reason.NO_BUCKETS)
    seen = [end for end in ends.values() if end is not None]
    oldest = min(seen, default=None)
    stalled = sorted(
        source
        for source, end in ends.items()
        if now - (watched_since if end is None else max(end, watched_since)) > silent_after
    )
    if stalled:
        return Finding(
            Check.ACTIVITYWATCH, Verdict.PROBLEM, Reason.STALLED, oldest, ", ".join(stalled)
        )
    if len(seen) == len(ends) and oldest is not None and now - oldest <= silent_after:
        return Finding(Check.ACTIVITYWATCH, Verdict.OK, Reason.RECORDING, oldest)
    return Finding(Check.ACTIVITYWATCH, Verdict.UNKNOWN, Reason.RESUMED, oldest)


def _liveness(
    since: datetime | None,
    now: datetime,
    active: list[Span],
    watched_since: datetime,
    silent_after: timedelta,
) -> Liveness:
    last_seen = watched_since if since is None else max(since, watched_since)
    return liveness(last_seen, now=now, paused=False, active=active, alive_within=silent_after)
