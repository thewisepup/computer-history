from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path

from computer_history.host import Host, HostError
from computer_history.sources import (
    AWApi,
    BackendHeartbeat,
    SourceUnavailable,
    Span,
    active_spans,
    capture_liveness,
    read_backend_heartbeat,
    watcher_ends,
)
from computer_history.watchdog.alerts import NOTIFICATION_TITLE, Notice, due_to_log, notices
from computer_history.watchdog.checks import (
    Check,
    Finding,
    Reason,
    Verdict,
    judge_activitywatch,
    judge_backend,
    judge_capture_agent,
)
from computer_history.watchdog.reopening import Reopening, recent_reopens, reopen_if_closed
from computer_history.watchdog.state import (
    WatchdogState,
    holding,
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
    lock: Path


@dataclass(frozen=True)
class WatchdogRun:
    """One run: the state it saved, the notifications it posted, its reopen, and what to log."""

    state: WatchdogState
    thresholds: Thresholds
    posted: tuple[Notice, ...]
    reopening: Reopening | None
    to_log: tuple[str, ...]


def stopped(state: WatchdogState, now: datetime) -> bool:
    """Whether the watchdog has gone longer without a run than its every-minute schedule allows."""
    return state.ran_at is None or now - state.ran_at > WATCH_GAP


def watch_once(
    host: Host,
    conn: sqlite3.Connection | None,
    client: AWApi,
    paths: WatchPaths,
    *,
    now: datetime,
    hostname: str,
) -> WatchdogRun | None:
    """Check, notify and save the state once, or return None while another run holds the lock."""
    with holding(paths.lock) as held:
        if not held:
            return None
        return _watch(host, conn, client, paths, now=now, hostname=hostname)


def _watch(
    host: Host,
    conn: sqlite3.Connection | None,
    client: AWApi,
    paths: WatchPaths,
    *,
    now: datetime,
    hostname: str,
) -> WatchdogRun:
    thresholds = read_thresholds(paths.config)
    silent_after = thresholds.silent_after
    errors: list[str] = []
    try:
        previous = read_watchdog_state(paths.state) or WatchdogState()
    except (OSError, ValueError) as exc:
        errors.append(f"started afresh: {exc}")
        previous = WatchdogState()
    if stopped(previous, now) or previous.watching_since is None:
        watched_since = now
    else:
        watched_since = previous.watching_since

    try:
        ends, aw_error = watcher_ends(client, client.get_buckets(), hostname=hostname), None
    except SourceUnavailable as exc:
        ends, aw_error = None, str(exc)
    unreachable_since = None if ends is not None else previous.unreachable_since or now
    reopening = None if ends is not None else reopen_if_closed(host, previous.reopened, now)
    if reopening is not None and reopening.error is not None:
        errors.append(reopening.error)

    reach = max(silent_after.values())
    store_error = None
    try:
        active = active_spans(conn, client if ends is not None else None, now - reach, now)
    except sqlite3.Error as exc:
        active, store_error = [], f"database read failed: {exc}"
    capture = _capture_agent(conn, paths, active, store_error, now, watched_since, thresholds)
    heartbeat, backend = _heartbeat(paths.heartbeat)
    failing_since = previous.failing_since
    if heartbeat is not None:
        failing_since = None if heartbeat.ok else failing_since or heartbeat.cycle_at
    if backend is None:
        backend = judge_backend(
            heartbeat,
            now=now,
            active=_since(active, now - silent_after[Check.BACKEND]),
            watched_since=watched_since,
            failing_since=failing_since,
            silent_after=silent_after[Check.BACKEND],
        )
        if store_error is not None and backend.verdict is not Verdict.OK:
            backend = replace(
                backend, verdict=Verdict.UNKNOWN, reason=Reason.UNREADABLE, detail=store_error
            )
    findings = [
        capture,
        judge_activitywatch(
            ends,
            unreachable_since=unreachable_since,
            error=aw_error,
            now=now,
            watched_since=watched_since,
            silent_after=silent_after[Check.ACTIVITYWATCH],
        ),
        backend,
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
            notified.pop(notice.check, None)
        else:
            notified[notice.check] = now
            open_problems.add(notice.check)

    messages = [f"config problem: {problem}" for problem in thresholds.problems]
    to_log, logged = due_to_log(
        [*messages, *(f"error: {error}" for error in errors)], previous.logged, now
    )
    state = WatchdogState(
        ran_at=now,
        watching_since=watched_since,
        findings=tuple(findings),
        notified=notified,
        open=frozenset(open_problems),
        reopened=recent_reopens(previous.reopened, now) if reopening is None else reopening.reopens,
        unreachable_since=unreachable_since,
        failing_since=failing_since,
        logged=logged,
        errors=tuple(errors),
    )
    try:
        write_watchdog_state(paths.state, state)
    except OSError as exc:
        failed = f"error: could not save {paths.state}: {exc}"
        state = replace(state, errors=(*state.errors, failed.removeprefix("error: ")))
        to_log = (*to_log, failed)
    return WatchdogRun(state, thresholds, tuple(posted), reopening, to_log)


def _capture_agent(
    conn: sqlite3.Connection | None,
    paths: WatchPaths,
    active: list[Span],
    store_error: str | None,
    now: datetime,
    watched_since: datetime,
    thresholds: Thresholds,
) -> Finding:
    silent_after = thresholds.silent_after[Check.CAPTURE_AGENT]
    if store_error is None:
        try:
            found = capture_liveness(
                conn,
                paths.spool,
                now=now,
                active=_since(active, now - silent_after),
                watched_since=watched_since,
                alive_within=silent_after,
            )
            return judge_capture_agent(found, now=now, silent_after=silent_after)
        except sqlite3.Error as exc:
            store_error = f"database read failed: {exc}"
    return Finding(Check.CAPTURE_AGENT, Verdict.UNKNOWN, Reason.UNREADABLE, detail=store_error)


def _heartbeat(path: Path) -> tuple[BackendHeartbeat | None, Finding | None]:
    try:
        return read_backend_heartbeat(path), None
    except (OSError, ValueError) as exc:
        unreadable = Finding(Check.BACKEND, Verdict.UNKNOWN, Reason.UNREADABLE, detail=str(exc))
        return None, unreadable


def _since(active: list[Span], start: datetime) -> list[Span]:
    return [(max(a, start), b) for a, b in active if b > start]
