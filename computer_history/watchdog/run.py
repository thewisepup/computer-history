from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from computer_history.host import Host, HostError
from computer_history.sources import (
    AWApi,
    SourceUnavailable,
    active_spans,
    capture_liveness,
    read_backend_heartbeat,
    watcher_ends,
)
from computer_history.watchdog.alerts import (
    NOTIFICATION_TITLE,
    REOPEN_LIMIT,
    Notice,
    notices,
    recent_reopens,
)
from computer_history.watchdog.checks import (
    Check,
    Finding,
    Reason,
    Span,
    Verdict,
    judge_activitywatch,
    judge_backend,
    judge_capture_agent,
)
from computer_history.watchdog.state import (
    WatchdogState,
    read_watchdog_state,
    write_watchdog_state,
)
from computer_history.watchdog.thresholds import Thresholds, read_thresholds

WATCH_GAP = timedelta(minutes=3)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WatchPaths:
    """The files one watchdog run reads and writes."""

    spool: Path
    heartbeat: Path
    config: Path
    state: Path


@dataclass(frozen=True)
class WatchdogRun:
    """One run: the state it saved, the notifications it posted, and any reopen of ActivityWatch.

    Reopen refused means ActivityWatch was down and the hourly limit was already reached.
    """

    state: WatchdogState
    thresholds: Thresholds
    posted: tuple[Notice, ...]
    reopened: bool
    reopen_refused: bool


def watch_once(
    host: Host,
    conn: sqlite3.Connection | None,
    client: AWApi,
    paths: WatchPaths,
    *,
    now: datetime,
    hostname: str,
) -> WatchdogRun:
    """Check the capture agent, ActivityWatch and the backend, notify, and save what was found.

    Silence is counted from no earlier than when the watchdog last resumed running every minute.
    """
    thresholds = read_thresholds(paths.config)
    errors: list[str] = []
    try:
        previous = read_watchdog_state(paths.state) or WatchdogState()
    except (OSError, ValueError) as exc:
        errors.append(f"started afresh: {exc}")
        previous = WatchdogState()
    resumed = previous.ran_at is None or now - previous.ran_at > WATCH_GAP
    watched_since = now if resumed or previous.watching_since is None else previous.watching_since
    silent_after = thresholds.silent_after

    try:
        ends, aw_error = watcher_ends(client, client.get_buckets(), hostname=hostname), None
    except SourceUnavailable as exc:
        ends, aw_error = None, str(exc)
    unreachable_since = None if ends is not None else previous.unreachable_since or now
    reopened = refused = False
    reopens = recent_reopens(previous.reopened, now)
    if ends is None:
        try:
            if not host.activitywatch_running():
                if len(reopens) < REOPEN_LIMIT:
                    host.open_activitywatch()
                    reopens, reopened = (*reopens, now), True
                else:
                    refused = True
        except HostError as exc:
            errors.append(str(exc))

    reach = timedelta(0) if not silent_after else max(silent_after.values())
    active = active_spans(conn, client if ends is not None else None, now - reach, now)
    findings = [
        judge_capture_agent(
            capture_liveness(
                conn,
                paths.spool,
                now=now,
                active=_since(active, now - silent_after[Check.CAPTURE_AGENT]),
                watched_since=watched_since,
                alive_within=silent_after[Check.CAPTURE_AGENT],
            ),
            now=now,
            silent_after=silent_after[Check.CAPTURE_AGENT],
        ),
        judge_activitywatch(
            ends,
            unreachable_since=unreachable_since,
            error=aw_error,
            now=now,
            watched_since=watched_since,
            silent_after=silent_after[Check.ACTIVITYWATCH],
        ),
        _backend(paths.heartbeat, active, now, watched_since, silent_after[Check.BACKEND]),
    ]

    notified, open_problems = dict(previous.notified), set(previous.open)
    posted: list[Notice] = []
    for notice in notices(
        findings,
        notified=previous.notified,
        open_problems=previous.open,
        silent_after=silent_after,
        now=now,
    ):
        try:
            host.notify(NOTIFICATION_TITLE, notice.message)
        except HostError as exc:
            errors.append(str(exc))
            continue
        log.info("notified: %s", notice.message)
        posted.append(notice)
        if notice.cleared:
            open_problems.discard(notice.check)
        else:
            notified[notice.check] = now
            open_problems.add(notice.check)

    state = WatchdogState(
        ran_at=now,
        watching_since=watched_since,
        findings=tuple(findings),
        notified=notified,
        open=frozenset(open_problems),
        reopened=reopens,
        unreachable_since=unreachable_since,
        errors=tuple(errors),
    )
    try:
        write_watchdog_state(paths.state, state)
    except OSError as exc:
        state = replace(state, errors=(*state.errors, f"could not save {paths.state}: {exc}"))
    return WatchdogRun(state, thresholds, tuple(posted), reopened, refused)


def _since(active: list[Span], start: datetime) -> list[Span]:
    return [(max(a, start), b) for a, b in active if b > start]


def _backend(
    path: Path, active: list[Span], now: datetime, watched_since: datetime, silent_after: timedelta
) -> Finding:
    try:
        heartbeat = read_backend_heartbeat(path)
    except (OSError, ValueError) as exc:
        return Finding(Check.BACKEND, Verdict.UNKNOWN, Reason.UNREADABLE, detail=str(exc))
    return judge_backend(
        heartbeat,
        now=now,
        active=_since(active, now - silent_after),
        watched_since=watched_since,
        silent_after=silent_after,
    )
