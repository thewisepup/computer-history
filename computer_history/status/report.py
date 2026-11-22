from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TypeAlias

from computer_history.host import Host, HostError
from computer_history.sources import (
    SCREENSHOT_SOURCE,
    WINDOW_TEXT_SOURCE,
    ActivityWatch,
    AWApi,
    CaptureHealth,
    ScreenshotHealth,
    SourceUnavailable,
    agent_config_path,
    capture_health,
    health_path,
    screenshot_health,
)
from computer_history.sources import Coverage as CaptureCoverage
from computer_history.stable import (
    AgentStatus,
    BackupInventory,
    InstalledAgent,
    InstalledVersion,
    UpdateLogEntry,
    agent_statuses,
    backup_inventory,
    installed_agent,
    last_agent_fallback,
    last_update_log_entry,
    pointed,
    stable_layout,
)
from computer_history.store import (
    MIN_GAP_SECONDS,
    STATUS_WINDOW,
    Gap,
    OpenedStore,
    Profile,
    SourceCoverage,
    SourceSummary,
    StoreState,
    default_db_path,
    source_summary,
    status_reads,
)
from computer_history.watchdog import (
    Assessment,
    WatchdogState,
    assess,
    read_thresholds,
    read_watchdog_state,
    recent_reopens,
    stopped,
    watchdog_state_path,
)


class GapCause(Enum):
    ACTIVE = "while you were active"
    UNJUDGED = "cannot be judged: no aw-afk data"


@dataclass(frozen=True)
class CaptureGaps:
    """Window text's coverage gaps, judged from the capture agent's records against aw-afk."""

    coverage: CaptureCoverage | None
    gaps: tuple[tuple[Gap, GapCause], ...] = ()


@dataclass(frozen=True)
class JudgedElsewhere:
    """A source whose coverage is judged from another source's records."""

    source: str
    by: str


SourceGaps: TypeAlias = SourceCoverage | CaptureGaps | JudgedElsewhere


@dataclass(frozen=True)
class StoreDetails:
    """What a ready database holds: its sources and their gaps, the capture agent, screenshots
    and row counts."""

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
    state: WatchdogState | None
    error: str | None = None
    reopens: tuple[datetime, ...] = ()
    stopped: bool = False


@dataclass(frozen=True)
class StatusReport:
    """Everything status shows: the watchdog's three findings, the database's details when it is
    ready, the backups beside it, and the stable install, its LaunchAgents and its watchdog."""

    assessment: Assessment
    aw_streams: list[str] | None
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
    spool: Path,
    now: datetime,
    hostname: str,
    day_start: datetime,
) -> StatusReport:
    """Read and judge everything status shows, writing nothing, by the watchdog's own rules and
    thresholds."""
    db_path = store.path
    conn = store.conn if store.state is StoreState.READY else None
    assessment = assess(
        conn,
        client,
        spool=spool,
        health_file=health_path(db_path),
        silent_after=read_thresholds(agent_config_path(db_path)).silent_after,
        previous=_watched(watchdog_state_path(db_path)),
        now=now,
        hostname=hostname,
    )
    reachable = assessment.unreachable_since is None
    details = None
    if conn is not None:
        details = _store_details(
            conn, client if reachable else None, spool, now, hostname, day_start
        )
    backups = backup_inventory(db_path)
    agents, agents_error = _agents(host)
    return StatusReport(
        assessment=assessment,
        aw_streams=_streams(client) if reachable else None,
        store=details,
        backups=backups,
        backups_overdue=backups.overdue(now),
        install=_install(),
        agents=agents,
        agents_error=agents_error,
        watchdog=_saved_watchdog(now),
    )


def _watched(path: Path) -> WatchdogState:
    try:
        return read_watchdog_state(path) or WatchdogState()
    except (OSError, ValueError):
        return WatchdogState()


def _streams(client: AWApi) -> list[str] | None:
    try:
        return ActivityWatch(client).streams()
    except SourceUnavailable:
        return None


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
    reads = status_reads(conn, summaries, skip=skip)
    return StoreDetails(
        summaries,
        _gaps(summaries, reads.coverage, capture),
        capture,
        screenshot_health(conn, day_start=day_start, now=now),
        reads.counts,
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


def _capture_gaps(coverage: CaptureCoverage | None) -> CaptureGaps:
    if coverage is None:
        return CaptureGaps(None)
    gaps = [(gap, GapCause.ACTIVE) for gap in coverage.unobserved]
    gaps += [(gap, GapCause.UNJUDGED) for gap in coverage.unjudged]
    return CaptureGaps(coverage, tuple(sorted(gaps, key=lambda found: (found[0], found[1].value))))


def _install() -> InstallDetails:
    layout = stable_layout()
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


def _agents(host: Host) -> tuple[list[AgentStatus] | None, str | None]:
    try:
        return agent_statuses(host, stable_layout()), None
    except HostError as exc:
        return None, str(exc)


def _saved_watchdog(now: datetime) -> SavedWatchdog:
    path = watchdog_state_path(default_db_path(Profile.STABLE))
    try:
        state = read_watchdog_state(path)
    except (OSError, ValueError) as exc:
        return SavedWatchdog(path, None, str(exc))
    if state is None or state.ran_at is None:
        return SavedWatchdog(path, state)
    reopens = recent_reopens(state.reopened, now)
    return SavedWatchdog(path, state, None, reopens, stopped(state, now))
