from __future__ import annotations

import argparse
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from socket import gethostname

from computer_history.cli import formatting
from computer_history.cli.db import outdated_note, store_unavailable
from computer_history.cli.formatting import (
    ago,
    app_name,
    before_now,
    db_size,
    duration,
    finding_lines,
    human_size,
    local_midnight,
    plural,
    printable,
    when,
)
from computer_history.cli.sources import AW_CHECK_TIMEOUT_SECONDS
from computer_history.sources import (
    ActivityWatch,
    AWClient,
    CaptureHealth,
    IngestHealth,
    health_path,
    resolve_spool_path,
)
from computer_history.sources.capture_spool import (
    CAPTURE_TOLERANCE,
    SCREENSHOT_SOURCE,
    UNREADABLE_FOLDER,
    WINDOW_TEXT_SOURCE,
    ScreenshotHealth,
    ScreenshotTally,
)
from computer_history.stable import (
    DAILY_BACKUP,
    DAILY_FOLDER_NAME,
    DAILY_KEPT,
    AgentStatus,
    BackupInventory,
    UpdateAction,
    UpdateLogEntry,
    stable_layout,
    version_name,
)
from computer_history.status import (
    CaptureGaps,
    InstallDetails,
    JudgedElsewhere,
    SavedWatchdog,
    StatusReport,
    StoreDetails,
    status_report,
)
from computer_history.store import (
    MIN_GAP_SECONDS,
    STATUS_WINDOW,
    Gap,
    OpenedStore,
    Profile,
    Purpose,
    SourceSummary,
    StoreState,
    default_db_path,
    open_store,
)
from computer_history.watchdog import REOPEN_LIMIT, Finding, Reason, watchdog_state_path

MAX_GAPS_SHOWN = 10
MAX_APP_PAIRS_SHOWN = 3


def cmd_status(args: argparse.Namespace) -> int:
    """Print the given database's sections, then the stable install's."""
    db_path: Path = args.database
    spool_path = resolve_spool_path(args.spool_path, db_path, args.profile)
    now = formatting.utc_now()
    client = AWClient(args.aw_url, timeout=AW_CHECK_TIMEOUT_SECONDS)
    with open_store(db_path, Purpose.READ) as store:
        report = status_report(
            store,
            client,
            args.host,
            layout=stable_layout(),
            stable_state=watchdog_state_path(default_db_path(Profile.STABLE)),
            spool=spool_path,
            now=now,
            hostname=gethostname(),
            day_start=local_midnight(now),
        )
    code = _print_store(store, report, args.aw_url, spool_path, now)
    print()
    _print_backups(report.backups, report.backups_overdue, now)
    print()
    _print_install(report.install, args.profile, now)
    print()
    _print_launch_agents(report.agents, report.agents_error)
    print()
    _print_watchdog(report.watchdog, now)
    return code


def _print_store(
    store: OpenedStore, report: StatusReport, aw_url: str, spool_path: Path, now: datetime
) -> int:
    db_path = store.path
    assessment = report.assessment
    ingest_banner, ingest_line = _ingest(assessment.health, assessment.health_error, db_path, now)
    aw_banner, aw_line = _activitywatch(assessment.activitywatch, assessment.aw_sources, aw_url)
    banners = [banner for banner in (ingest_banner, aw_banner) if banner is not None]
    if banners:
        print("\n".join(banners))
        print()
    if store.state is StoreState.MISSING:
        print(f"Database:      {db_path} (not created yet; run `computer-history ingest`)")
    elif store.state not in (StoreState.BUSY, StoreState.UNREADABLE):
        print(f"Database:      {db_path} ({db_size(db_path)}, schema v{store.version})")
    print(aw_line)
    print(ingest_line)
    if store.state is StoreState.OUTDATED:
        print(f"  note: {outdated_note(store)}. No store details until then.")
    print()
    print("Watchdog checks (run now, nothing notified):")
    for line in finding_lines(assessment.findings, now):
        print(line)
    if store.state in (StoreState.MISSING, StoreState.OUTDATED):
        return 0
    details = report.store
    if details is None:
        return store_unavailable(store)
    print()
    _print_sources(details.sources, now)
    print()
    _print_gaps(details)
    print()
    _print_agent(details.capture, spool_path, now)
    print()
    _print_screenshots(details.screenshots, now)
    print()
    _print_counts(details.counts)
    return 0


def _activitywatch(
    found: Finding, streams: tuple[str, ...] | None, aw_url: str
) -> tuple[str | None, str]:
    if found.reason is Reason.UNREACHABLE:
        banner = f"!! ActivityWatch is UNREACHABLE at {aw_url}: nothing new can be ingested."
        return banner, f"ActivityWatch: {aw_url}"
    names = ", ".join(streams or []) or "none of window/AFK/web"
    return None, f"ActivityWatch: {aw_url} (sources: {names})"


def _print_install(install: InstallDetails, profile: Profile, now: datetime) -> None:
    print("Stable install:")
    print(f"  this run      {profile.value}")
    for name, version in (("current", install.current), ("previous", install.previous)):
        if version is None:
            print(f"  {name:<13} none")
        else:
            print(f"  {name:<13} {version.name}, installed {ago(version.installed_at, now)}")
    agent = install.agent
    if agent is None:
        print("  agent         built from unknown")
    else:
        built = version_name(agent.built_from)
        print(f"  agent         built from {built}, installed {ago(agent.installed_at, now)}")
    if install.agent_fallback is not None:
        print(f"                {_update_entry(install.agent_fallback, now, fell_back=True)}")
    print(f"  last update   {_last_update(install, now)}")


def _last_update(install: InstallDetails, now: datetime) -> str:
    if install.update_log_error is not None:
        return f"unreadable update log: {install.update_log_error}"
    entry = install.last_update
    if entry is None:
        return "none yet"
    return _update_entry(entry, now, fell_back=entry.action is UpdateAction.FELL_BACK)


def _update_entry(entry: UpdateLogEntry, now: datetime, *, fell_back: bool) -> str:
    shown = "fell back" if fell_back else entry.action.value
    line = f"{shown} {entry.from_version} -> {entry.to_version}, {ago(entry.at, now)}"
    return f"{line}: {entry.reason}" if fell_back else line


def _print_launch_agents(statuses: list[AgentStatus] | None, error: str | None) -> None:
    print("Stable install's LaunchAgents:")
    if statuses is None:
        print(f"  cannot ask launchd: {error}")
        return
    width = max(len(status.name) for status in statuses)
    for status in statuses:
        if not status.shown:
            continue
        print(f"  {status.name:<{width}}  {_job(status)}  {status.label}")
        if status.lingering:
            print(f"  warning: the {status.name} still runs; `computer-history install` retires it")


def _job(status: AgentStatus) -> str:
    state = status.state
    if state is None or not state.loaded:
        return "installed, not loaded" if status.installed else "not installed"
    shown = "loaded, not running" if state.pid is None else f"loaded, running (pid {state.pid})"
    return shown if status.installed else f"{shown}, plist deleted"


def _print_backups(kept: BackupInventory, overdue: bool, now: datetime) -> None:
    print("Backups:")
    if not kept.daily and not kept.pre_update:
        daily = kept.folder / DAILY_FOLDER_NAME
        print(f"  none yet (the daily backup takes one a day into {daily})")
        return
    if kept.daily:
        latest = kept.daily[-1]
        print(
            f"  latest        {latest.day}, taken {ago(latest.taken_at, now)},"
            f" {human_size(latest.size)}"
        )
        print(
            f"  daily         {len(kept.daily)} kept (the newest {DAILY_KEPT}), oldest"
            f" {kept.daily[0].day}"
        )
    else:
        print("  daily         none yet")
    if kept.pre_update:
        print(
            f"  pre-update    {len(kept.pre_update)} kept, newest taken"
            f" {when(kept.pre_update[-1].taken_at)}"
        )
    print("  integrity     each passed SQLite's integrity check before it was kept")
    print(f"  folder        {kept.folder}")
    if overdue:
        missing = f"since {kept.daily[-1].day}" if kept.daily else "taken yet"
        print(
            f"  warning: no daily backup {missing}; check that {DAILY_BACKUP.label} is loaded"
            " and read its log"
        )


def _print_watchdog(saved: SavedWatchdog, now: datetime) -> None:
    print("Stable watchdog:")
    if saved.error is not None:
        print(f"  last run       unreadable state: {saved.error}")
        return
    state = saved.state
    if state.ran_at is None:
        print(f"  last run       none yet (no state at {saved.path})")
        return
    print(f"  last run       {ago(state.ran_at, now)}")
    for line in finding_lines(state.findings, now, state.notified):
        print(line)
    reopens = saved.reopens
    if reopens:
        print(
            f"  reopened       ActivityWatch {len(reopens)} {plural('time', len(reopens))}"
            f" in the last hour (at most {REOPEN_LIMIT})"
        )
    for error in state.errors:
        print(f"  error: {error}")
    if saved.stopped:
        print(
            f"  warning: the watchdog last ran {duration((now - state.ran_at).total_seconds())}"
            " ago; it runs every minute while its LaunchAgent is loaded"
        )


def _ingest(
    health: IngestHealth | None, error: str | None, db_path: Path, now: datetime
) -> tuple[str | None, str]:
    if error is not None:
        return None, f"Ingest:        cannot read {health_path(db_path)}: {error}"
    if health is None:
        return None, "Ingest:        no `ingest --watch` has reported yet"
    line = f"Ingest:        {_ingest_state(health)}, last cycle {ago(health.cycle_at, now)}"
    if not health.consecutive_failures:
        return None, line
    last = "never" if health.last_success_at is None else ago(health.last_success_at, now)
    banner = f"!! ingest is {_ingest_state(health)}: {printable(health.last_error or '')}"
    return banner, f"{line}\n  last success  {last}"


def _ingest_state(health: IngestHealth) -> str:
    if not health.consecutive_failures or health.failing_since is None:
        return "ok"
    return f"FAILING since {when(health.failing_since)} ({health.consecutive_failures:,} cycles)"


def _print_sources(summaries: list[SourceSummary], now: datetime) -> None:
    print("Sources:")
    if not summaries:
        print("  none yet (run `computer-history ingest`)")
        return
    width = max(len(s.source) for s in summaries)
    for s in summaries:
        print(
            f"  {s.source:<{width}}  {s.observation_count:>8,} observations"
            f"  latest end {when(s.latest_ended_at)}"
            f"  settled until {when(s.settled_until)} ({_freshness(s, now)})"
        )
    if any(s.source in ActivityWatch.projectors for s in summaries):
        print(
            "  (an ActivityWatch source is settled only up to the start of its current,"
            " still-growing window/tab/AFK event, so lag includes that event's length)"
        )


def _freshness(summary: SourceSummary, now: datetime) -> str:
    if summary.advanced_at is None:
        return "never ingested"
    if summary.settled_until is None:
        return f"progress moved {duration((now - summary.advanced_at).total_seconds())} ago"
    return before_now(now - summary.settled_until, " behind now")


def _print_gaps(details: StoreDetails) -> None:
    print(
        f"Coverage gaps (unobserved: nothing recorded) of {duration(MIN_GAP_SECONDS)} or"
        f" more, in the {STATUS_WINDOW.total_seconds() / 3600:g}h up to each source's"
        " settled-until time (or its latest observation, if it has none):"
    )
    if not details.sources:
        print("  nothing to check yet")
    for checked in details.gaps:
        if isinstance(checked, CaptureGaps):
            _print_capture_gaps(checked)
            continue
        if isinstance(checked, JudgedElsewhere):
            print(f"  {checked.source}: not checked (coverage is judged from {checked.by} records)")
            continue
        source = checked.summary.source
        if checked.span is None:
            print(f"  {source}: no observations yet")
            continue
        if not checked.checkable:
            print(f"  {source}: no settled span to check yet")
            continue
        _print_gap_list(source, checked.span[0], [(gap, "") for gap in checked.gaps])


def _print_capture_gaps(checked: CaptureGaps) -> None:
    coverage = checked.coverage
    if coverage is None:
        print(f"  {WINDOW_TEXT_SOURCE}: no settled span to check yet")
        return
    print(
        f"  {WINDOW_TEXT_SOURCE} from {when(coverage.start)} to {when(coverage.end)} (unobserved:"
        f" aw-afk shows you active, no record within {duration(CAPTURE_TOLERANCE.total_seconds())},"
        " not paused or asleep):"
    )
    gaps = [(gap, f", {cause.value}") for gap, cause in checked.gaps]
    _print_gap_list(WINDOW_TEXT_SOURCE, coverage.start, gaps)


def _print_gap_list(source: str, start: datetime, gaps: Sequence[tuple[Gap, str]]) -> None:
    """Each gap up to the first few, with what follows it on its line, then how many more."""
    if not gaps:
        print(f"  {source}: no gaps since {when(start)}")
    for gap, cause in gaps[:MAX_GAPS_SHOWN]:
        print(
            f"  warning: no {source} coverage from {when(gap.start)} to {when(gap.end)}"
            f" ({duration(gap.seconds)}){cause}"
        )
    if len(gaps) > MAX_GAPS_SHOWN:
        print(f"  warning: ... and {len(gaps) - MAX_GAPS_SHOWN} more {source} gaps")


def _print_agent(health: CaptureHealth, spool_path: Path, now: datetime) -> None:
    if not health.reported:
        print(f"Capture agent: has not reported yet (no {WINDOW_TEXT_SOURCE} records stored)")
        print(f"  spool         {_spool(health, spool_path, now)}")
        return
    print("Capture agent:")
    print(f"  last capture  {ago(health.last_capture, now)}")
    print(f"  spool         {_spool(health, spool_path, now)}")
    t = health.today
    print(
        f"  today         {t.captures:,} captures stored, {t.excluded:,} excluded,"
        f" {t.cut_off:,} cut off, {t.timed_out:,} timed out, {t.slept:,} slept, {t.woke:,} woke"
    )
    paused = "no" if health.paused_since is None else f"yes, since {ago(health.paused_since, now)}"
    print(f"  paused        {paused}")
    _print_agreement(health)


def _print_agreement(health: CaptureHealth) -> None:
    agreement = health.agreement
    if agreement is None:
        print("  app agreement no captures to check yet")
        return
    judged = agreement.matched + agreement.differ
    if judged == 0:
        if not agreement.unjudged:
            print("  app agreement no captures to check")
        elif agreement.spans:
            print("  app agreement cannot be judged: no aw-window data near any capture")
        else:
            print("  app agreement cannot be judged: no aw-window data from this machine")
        return
    print(
        f"  app agreement {agreement.matched:,} of {judged:,} captures match aw-window"
        f" ({agreement.differ:,} differ, {agreement.unjudged:,} without aw-window data)"
    )
    for captured, seen, n in agreement.pairs[:MAX_APP_PAIRS_SHOWN]:
        print(f"                {n:,} x {app_name(captured)} -> {app_name(seen)}")


def _spool(health: CaptureHealth, spool_path: Path, now: datetime) -> str:
    spool = health.spool
    if spool is None:
        return f"cannot be inspected: {health.spool_error}"
    waiting = f"{spool.waiting:,} finished {plural('file', spool.waiting)} waiting"
    if spool.oldest_finished_at is not None:
        waiting += f" (oldest {before_now(now - spool.oldest_finished_at)})"
    return f"{waiting}, {spool.unreadable:,} in {UNREADABLE_FOLDER}/  ({spool_path})"


def _print_screenshots(shots: ScreenshotHealth, now: datetime) -> None:
    if not shots.reported:
        print(f"Screenshots: none stored yet (no {SCREENSHOT_SOURCE} records)")
        return
    print("Screenshots:")
    kept = shots.last_kept
    if kept is None:
        print("  last kept     none yet")
    else:
        path = "(no path)" if kept.image_path is None else printable(kept.image_path)
        print(f"  last kept     {ago(kept.at, now)}, {app_name(kept.app)}, {path}")
    print(f"  today         {_statuses(shots.today)}")
    print(f"  all stored    {_statuses(shots.total)}")
    print(
        f"  disk          {human_size(shots.total.image_bytes)} in total,"
        f" {human_size(shots.today.image_bytes)} today (from kept records)"
    )
    missing = shots.no_permission
    if missing is None:
        return
    if missing.current:
        print(
            "  warning: Screen Recording permission is missing since"
            f" {ago(missing.since, now)} (records say no-permission, and no"
            " screenshot was taken since). Grant it in System Settings > Privacy & Security"
            " > Screen Recording."
        )
    else:
        print(
            f"  permission    last recorded missing {ago(missing.last, now)}, missing since"
            f" {ago(missing.since, now)}; no screenshot record since says whether it is held"
        )


def _statuses(tally: ScreenshotTally) -> str:
    return ", ".join(f"{n:,} {status}" for status, n in tally.statuses.items())


def _print_counts(counts: dict[str, int]) -> None:
    print("Rows:")
    ordered = sorted(counts, key=lambda name: (name not in ("observations", "signals"), name))
    width = max((len(name) for name in ordered), default=0)
    for name in ordered:
        print(f"  {name:<{width}}  {counts[name]:>10,}")
