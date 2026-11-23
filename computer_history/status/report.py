from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TypeAlias

from computer_history.host import Host, HostError
from computer_history.sources import CaptureHealth, capture_health, health_path
from computer_history.sources.activitywatch import AWApi
from computer_history.sources.capture_spool import (
    SCREENSHOT_SOURCE,
    WINDOW_TEXT_SOURCE,
    Coverage,
    ScreenshotHealth,
    agent_config_path,
    screenshot_health,
)
from computer_history.stable import (
    AgentStatus,
    BackupInventory,
    InstalledAgent,
    InstalledVersion,
    Layout,
    UpdateLogEntry,
    agent_statuses,
    backup_inventory,
    installed_agent,
    last_agent_fallback,
    last_update_log_entry,
    pointed,
)
from computer_history.store import (
    MIN_GAP_SECONDS,
    STATUS_WINDOW,
    Gap,
    OpenedStore,
    SourceCoverage,
    SourceSummary,
    StoreState,
    source_summary,
    status_reads,
)
from computer_history.watchdog import (
    Assessment,
    WatchdogState,
    assess,
    read_state_or_fresh,
    read_thresholds,
    recent_reopens,
    running_since,
    stopped,
    watchdog_state_path,
)


class GapCause(Enum):
    ACTIVE = "while you were active"
    UNJUDGED = "cannot be judged: no aw-afk data"


@dataclass(frozen=True)
class CaptureGaps:
    """Window text's coverage gaps, judged from the capture agent's records against aw-afk."""

    coverage: Coverage | None
    gaps: tuple[tuple[Gap, GapCause], ...] = ()


@dataclass(frozen=True)
class JudgedElsewhere:
    """A source whose coverage is judged from another source's records."""

    source: str
    by: str


SourceGaps: TypeAlias = SourceCoverage | CaptureGaps | JudgedElsewhere


@dataclass(frozen=True)
class StoreDetails:
    """What a ready database holds, for status."""

    sources: list[SourceSummary]
    gaps: list[SourceGaps]
    capture: CaptureHealth
    screenshots: ScreenshotHealth
    counts: dict[str, int]


@dataclass(frozen=True)
class InstallDetails:
    """The stable install's current and previous versions, its agent, and its update log."""

    current: InstalledVersion | None
    previous: InstalledVersion | None
    agent: InstalledAgent | None
    agent_fallback: UpdateLogEntry | None
    last_update: UpdateLogEntry | None
    update_log_error: str | None = None


@dataclass(frozen=True)
class SavedWatchdog:
    """The stable watchdog's saved state, its reopens in the last hour, and whether it stopped."""

    path: Path
    state: WatchdogState
    error: str | None = None
    reopens: tuple[datetime, ...] = ()
    stopped: bool = False


@dataclass(frozen=True)
class StatusReport:
    """Everything the status command shows."""

    assessment: Assessment
    store: StoreDetails | None
    backups: BackupInventory
    backups_overdue: bool
    install: InstallDetails
    agents: list[AgentStatus] | None
    agents_error: str | None
    watchdog: SavedWatchdog


def status_report(
    store: OpenedStore,
    client: AWApi,
    host: Host,
    *,
    layout: Layout,
    stable_state: Path,
    spool: Path,
    now: datetime,
    hostname: str,
    day_start: datetime,
) -> StatusReport:
    """Read and judge everything status shows, writing nothing."""
    db_path = store.path
    conn = store.conn if store.state is StoreState.READY else None
    saved, saved_error = read_state_or_fresh(stable_state)
    beside = watchdog_state_path(db_path)
    if beside.resolve() == stable_state.resolve():
        previous = saved
    else:
        previous, _ = read_state_or_fresh(beside)
    running = running_since(previous, now)
    assessment = assess(
        conn,
        client,
        spool=spool,
        health_file=health_path(db_path),
        silent_after=read_thresholds(agent_config_path(db_path)).silent_after,
        watched_since=now - STATUS_WINDOW if running is None else running,
        unreachable_since=None if running is None else previous.unreachable_since,
        now=now,
        hostname=hostname,
    )
    details = None
    if conn is not None:
        reachable = assessment.unreachable_since is None
        details = _store_details(
            conn, client if reachable else None, spool, now, hostname, day_start
        )
    backups = backup_inventory(db_path)
    agents, agents_error = _agents(host, layout)
    return StatusReport(
        assessment=assessment,
        store=details,
        backups=backups,
        backups_overdue=backups.overdue(now),
        install=_install(layout),
        agents=agents,
        agents_error=agents_error,
        watchdog=_saved_watchdog(stable_state, saved, saved_error, now),
    )


def _store_details(
    conn: sqlite3.Connection,
    client: AWApi | None,
    spool: Path,
    now: datetime,
    hostname: str,
    day_start: datetime,
) -> StoreDetails:
    summaries = source_summary(conn)
    capture = capture_health(
        conn,
        summaries,
        spool,
        client,
        now=now,
        window=STATUS_WINDOW,
        hostname=hostname,
        min_gap_seconds=MIN_GAP_SECONDS,
        day_start=day_start,
    )
    skip = {SCREENSHOT_SOURCE, WINDOW_TEXT_SOURCE} if capture.reported else {SCREENSHOT_SOURCE}
    coverage, counts = status_reads(conn, summaries, skip=skip)
    return StoreDetails(
        summaries,
        _gaps(summaries, coverage, capture),
        capture,
        screenshot_health(conn, day_start=day_start, now=now),
        counts,
    )


def _gaps(
    summaries: list[SourceSummary], coverage: list[SourceCoverage], capture: CaptureHealth
) -> list[SourceGaps]:
    by_source = {checked.summary.source: checked for checked in coverage}
    found: list[SourceGaps] = []
    for summary in summaries:
        if summary.source in by_source:
            found.append(by_source[summary.source])
        elif summary.source == WINDOW_TEXT_SOURCE:
            found.append(_capture_gaps(capture.coverage))
        elif summary.source == SCREENSHOT_SOURCE and capture.coverage is not None:
            found.append(JudgedElsewhere(SCREENSHOT_SOURCE, WINDOW_TEXT_SOURCE))
    return found


def _capture_gaps(coverage: Coverage | None) -> CaptureGaps:
    if coverage is None:
        return CaptureGaps(None)
    gaps = [(gap, GapCause.ACTIVE) for gap in coverage.unobserved]
    gaps += [(gap, GapCause.UNJUDGED) for gap in coverage.unjudged]
    return CaptureGaps(coverage, tuple(sorted(gaps, key=lambda found: (found[0], found[1].value))))


def _install(layout: Layout) -> InstallDetails:
    try:
        fallback = last_agent_fallback(layout.update_log)
    except (OSError, ValueError):
        fallback = None
    try:
        last, error = last_update_log_entry(layout.update_log), None
    except (OSError, ValueError) as exc:
        last, error = None, str(exc)
    return InstallDetails(
        pointed(layout.current),
        pointed(layout.previous),
        installed_agent(layout),
        fallback,
        last,
        error,
    )


def _agents(host: Host, layout: Layout) -> tuple[list[AgentStatus] | None, str | None]:
    try:
        return agent_statuses(host, layout), None
    except HostError as exc:
        return None, str(exc)


def _saved_watchdog(
    path: Path, state: WatchdogState, error: str | None, now: datetime
) -> SavedWatchdog:
    if error is not None or state.ran_at is None:
        return SavedWatchdog(path, state, error)
    reopens = recent_reopens(state.reopened, now)
    return SavedWatchdog(path, state, None, reopens, stopped(state, now))
