from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from computer_history.sources import BackendHeartbeat, CaptureLiveness, liveness

Span = tuple[datetime, datetime]


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
    FAILING = "finishing cycles, but the last one failed"
    SILENT = "silent while you were active"
    IDLE = "silent, but aw-afk does not show you active"
    PAUSED = "paused"
    RESUMED = "silent, but watched only since the watchdog resumed"
    NEVER_SEEN = "nothing recorded yet"
    UNREACHABLE = "unreachable"
    STALLED = "buckets not advancing"
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
    """Judge the capture agent from its newest record and the liveness status computes."""
    last = found.last_record
    if last is None:
        return Finding(
            Check.CAPTURE_AGENT, Verdict.UNKNOWN, Reason.NEVER_SEEN, None, found.spool_error
        )
    match found.alive:
        case "no":
            return Finding(Check.CAPTURE_AGENT, Verdict.PROBLEM, Reason.SILENT, last)
        case "paused":
            return Finding(Check.CAPTURE_AGENT, Verdict.UNKNOWN, Reason.PAUSED, last)
        case "yes" if now - last <= silent_after:
            return Finding(Check.CAPTURE_AGENT, Verdict.OK, Reason.RECORDING, last)
        case "yes":
            return Finding(Check.CAPTURE_AGENT, Verdict.UNKNOWN, Reason.RESUMED, last)
        case _:
            return Finding(Check.CAPTURE_AGENT, Verdict.UNKNOWN, Reason.IDLE, last)


def judge_backend(
    heartbeat: BackendHeartbeat | None,
    *,
    now: datetime,
    active: Iterable[Span],
    watched_since: datetime,
    silent_after: timedelta,
) -> Finding:
    """Judge the backend from its heartbeat: silent past the threshold while active is a problem."""
    last = None if heartbeat is None else heartbeat.cycle_at
    alive = liveness(
        watched_since if last is None else max(last, watched_since),
        now=now,
        paused=False,
        active=active,
        alive_within=silent_after,
    )
    if alive == "no":
        return Finding(Check.BACKEND, Verdict.PROBLEM, Reason.SILENT, last)
    if heartbeat is not None and last is not None and now - last <= silent_after:
        reason = Reason.RECORDING if heartbeat.ok else Reason.FAILING
        return Finding(Check.BACKEND, Verdict.OK, reason, last)
    if alive == "yes":
        reason = Reason.NEVER_SEEN if last is None else Reason.RESUMED
        return Finding(Check.BACKEND, Verdict.UNKNOWN, reason, last)
    return Finding(Check.BACKEND, Verdict.UNKNOWN, Reason.IDLE, last)


def judge_activitywatch(
    ends: Mapping[str, datetime | None] | None,
    *,
    unreachable_since: datetime | None,
    error: str | None,
    now: datetime,
    watched_since: datetime,
    silent_after: timedelta,
) -> Finding:
    """Judge ActivityWatch: unreachable, or a watcher's bucket not advancing, past the threshold.

    Ends is None when ActivityWatch was unreachable, and whether the user is active never matters.
    """
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
        bucket_id
        for bucket_id, end in ends.items()
        if now - (watched_since if end is None else max(end, watched_since)) > silent_after
    )
    if stalled:
        return Finding(
            Check.ACTIVITYWATCH, Verdict.PROBLEM, Reason.STALLED, oldest, ", ".join(stalled)
        )
    if len(seen) == len(ends) and oldest is not None and now - oldest <= silent_after:
        return Finding(Check.ACTIVITYWATCH, Verdict.OK, Reason.RECORDING, oldest)
    return Finding(Check.ACTIVITYWATCH, Verdict.UNKNOWN, Reason.RESUMED, oldest)
