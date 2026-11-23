from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from computer_history.host import Host, HostError
from computer_history.sources.activitywatch import AWApi
from computer_history.watchdog.alerts import Notice, due_to_log, notices
from computer_history.watchdog.assessment import assess
from computer_history.watchdog.reopening import Reopening, recent_reopens, reopen_if_closed
from computer_history.watchdog.state import (
    WatchdogState,
    holding,
    read_state_or_fresh,
    running_since,
    write_watchdog_state,
)
from computer_history.watchdog.thresholds import Thresholds, read_thresholds

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WatchPaths:
    """The files one watchdog run reads and writes."""

    spool: Path
    health: Path
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
    previous, unreadable = read_state_or_fresh(paths.state)
    if unreadable is not None:
        errors.append(f"started afresh: {unreadable}")
    assessment = assess(
        conn,
        client,
        spool=paths.spool,
        health_file=paths.health,
        silent_after=silent_after,
        watched_since=running_since(previous, now) or now,
        unreachable_since=previous.unreachable_since,
        now=now,
        hostname=hostname,
    )
    reopening = None
    if assessment.unreachable_since is not None:
        reopening = reopen_if_closed(host, previous.reopened, now)
    if reopening is not None and reopening.error is not None:
        errors.append(reopening.error)
    findings = assessment.findings

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
            host.notify(notice.message)
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
        watching_since=assessment.watched_since,
        findings=findings,
        notified=notified,
        open=frozenset(open_problems),
        reopened=recent_reopens(previous.reopened, now) if reopening is None else reopening.reopens,
        unreachable_since=assessment.unreachable_since,
        logged=logged,
        errors=tuple(errors),
    )
    try:
        write_watchdog_state(paths.state, state)
    except OSError as exc:
        failed = f"could not save {paths.state}: {exc}"
        state = replace(state, errors=(*state.errors, failed))
        to_log = (*to_log, f"error: {failed}")
    return WatchdogRun(state, thresholds, tuple(posted), reopening, to_log)
