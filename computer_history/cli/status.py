from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from socket import gethostname

from computer_history.cli import formatting
from computer_history.cli.db import outdated_note, store_unavailable
from computer_history.cli.formatting import (
    ago,
    app_name,
    db_size,
    duration,
    human_size,
    lag,
    local_midnight,
    printable,
    when,
)
from computer_history.host import Host, HostError
from computer_history.sources import (
    CAPTURE_TOLERANCE,
    SCREENSHOT_SOURCE,
    UNREADABLE_FOLDER,
    WINDOW_TEXT_SOURCE,
    ActivityWatch,
    AWClient,
    CaptureHealth,
    ScreenshotHealth,
    ScreenshotTally,
    SourceUnavailable,
    backend_heartbeat_path,
    capture_health,
    read_backend_heartbeat,
    resolve_spool_path,
    screenshot_health,
)
from computer_history.stable import (
    DAILY_BACKUP,
    DAILY_FOLDER_NAME,
    DAILY_KEPT,
    AgentStatus,
    BackupInventory,
    UpdateAction,
    agent_statuses,
    backup_inventory,
    last_update_log_entry,
    pointed,
    stable_layout,
)
from computer_history.store import (
    MIN_GAP_SECONDS,
    STATUS_WINDOW,
    Coverage,
    Profile,
    Purpose,
    SourceCoverage,
    SourceSummary,
    StoreState,
    default_db_path,
    open_store,
    source_summary,
    status_reads,
)

MAX_GAPS_SHOWN = 10
MAX_APP_PAIRS_SHOWN = 3
STATUS_AW_TIMEOUT_SECONDS = 5


def cmd_status(args: argparse.Namespace) -> int:
    db_path: Path = args.database
    spool_path = resolve_spool_path(args.spool_path, db_path, args.profile)
    now = formatting.utc_now()
    code = _print_store(args, db_path, spool_path, now)
    print()
    _print_install(args.profile, now)
    print()
    _print_launch_agents(args.host)
    print()
    _print_backend(now)
    print()
    _print_backups(backup_inventory(db_path), now)
    return code


def _print_store(args: argparse.Namespace, db_path: Path, spool_path: Path, now: datetime) -> int:
    day_start = local_midnight(now)
    client = AWClient(args.aw_url, timeout=STATUS_AW_TIMEOUT_SECONDS)
    aw = ActivityWatch(client)
    try:
        streams = aw.streams()
        aw_error = None
    except SourceUnavailable as exc:
        streams, aw_error = [], str(exc)

    if aw_error is not None:
        print(f"!! ActivityWatch is UNREACHABLE at {args.aw_url}: nothing new can be ingested.")
        print(f"!! {aw_error}")
        print()
        aw_line = f"ActivityWatch: no  ({args.aw_url})"
    else:
        names = ", ".join(streams) or "none of window/AFK/web"
        aw_line = f"ActivityWatch: yes ({args.aw_url}; sources: {names})"

    store = open_store(db_path, Purpose.READ)
    if store.state is StoreState.MISSING:
        print(f"Database:      {db_path} (not created yet; run `computer-history ingest`)")
        print(aw_line)
        return 0
    if store.state in (StoreState.BUSY, StoreState.UNREADABLE):
        print(aw_line)
        return store_unavailable(store)
    print(f"Database:      {db_path} ({db_size(db_path)}, schema v{store.version})")
    print(aw_line)
    if store.state is StoreState.OUTDATED:
        print(f"  note: {outdated_note(store)}. No store details until then.")
        return 0
    if store.conn is None:
        return store_unavailable(store)
    with store:
        summaries = source_summary(store.conn)
        health = capture_health(
            store.conn,
            summaries,
            spool_path,
            client if aw_error is None else None,
            now=now,
            window=STATUS_WINDOW,
            hostname=gethostname(),
            min_gap_seconds=MIN_GAP_SECONDS,
            day_start=day_start,
        )
        skip = {SCREENSHOT_SOURCE, WINDOW_TEXT_SOURCE} if health.reported else {SCREENSHOT_SOURCE}
        reads = status_reads(store.conn, summaries, skip=skip)
        print()
        _print_sources(summaries, now)
        print()
        _print_gaps(summaries, reads.coverage, health)
        print()
        _print_agent(health, spool_path, now)
        print()
        _print_screenshots(screenshot_health(store.conn, day_start=day_start, now=now), now)
        print()
        _print_counts(reads.counts)
    return 0


def _print_install(profile: Profile, now: datetime) -> None:
    layout = stable_layout()
    print("Stable install:")
    print(f"  this run      {profile.value}")
    for name, pointer in (("current", layout.current), ("previous", layout.previous)):
        version = pointed(pointer)
        if version is None:
            print(f"  {name:<13} none")
        else:
            print(f"  {name:<13} {version.name}, installed {ago(version.installed_at, now)}")
    print(f"  last update   {_last_update(layout.update_log, now)}")


def _last_update(log: Path, now: datetime) -> str:
    try:
        entry = last_update_log_entry(log)
    except (OSError, ValueError) as exc:
        return f"unreadable update log: {exc}"
    if entry is None:
        return "none yet"
    moved = f"{entry.from_version} -> {entry.to_version}"
    if entry.action is UpdateAction.FELL_BACK:
        return f"fell back {moved}, {ago(entry.at, now)}: {entry.reason}"
    return f"{entry.action.value} {moved}, {ago(entry.at, now)}"


def _print_launch_agents(host: Host) -> None:
    print("Stable install's LaunchAgents:")
    try:
        statuses = agent_statuses(host, stable_layout())
    except HostError as exc:
        print(f"  cannot ask launchd: {exc}")
        return
    width = max(len(status.name) for status in statuses)
    for status in statuses:
        loaded = status.state is not None and status.state.loaded
        if status.retired and not (status.installed or loaded):
            continue
        print(f"  {status.name:<{width}}  {_job(status)}  {status.label}")
        if status.retired and loaded:
            print(f"  warning: the {status.name} still runs; `computer-history install` retires it")


def _job(status: AgentStatus) -> str:
    state = status.state
    if state is None or not state.loaded:
        return "installed, not loaded" if status.installed else "not installed"
    shown = "loaded, not running" if state.pid is None else f"loaded, running (pid {state.pid})"
    return shown if status.installed else f"{shown}, plist deleted"


def _print_backend(now: datetime) -> None:
    print("Stable backend:")
    heartbeat_path = backend_heartbeat_path(default_db_path(Profile.STABLE))
    try:
        heartbeat = read_backend_heartbeat(heartbeat_path)
    except (OSError, ValueError) as exc:
        print(f"  last cycle    unreadable heartbeat: {exc}")
        return
    if heartbeat is None:
        print(f"  last cycle    none yet (no heartbeat at {heartbeat_path})")
        return
    result = "ok" if heartbeat.ok else "failed"
    print(f"  last cycle    {ago(heartbeat.cycle_at, now)}, {result}")


def _print_backups(kept: BackupInventory, now: datetime) -> None:
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
    if kept.overdue(now.astimezone().date()):
        missing = f"since {kept.daily[-1].day}" if kept.daily else "taken yet"
        print(
            f"  warning: no daily backup {missing}; check that {DAILY_BACKUP.label} is loaded"
            " and read its log"
        )


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
    return lag(now - summary.settled_until)


def _print_gaps(
    summaries: list[SourceSummary], coverage: list[SourceCoverage], health: CaptureHealth
) -> None:
    print(
        f"Coverage gaps (unobserved: nothing recorded) of {duration(MIN_GAP_SECONDS)} or"
        f" more, in the {STATUS_WINDOW.total_seconds() / 3600:g}h up to each source's"
        " settled-until time (or its latest observation, if it has none):"
    )
    if not summaries:
        print("  nothing to check yet")
    by_source = {source.summary.source: source for source in coverage}
    for s in summaries:
        if s.source == WINDOW_TEXT_SOURCE and health.reported:
            _print_capture_gaps(health)
            continue
        if s.source == SCREENSHOT_SOURCE:
            if health.coverage is not None:
                print(
                    f"  {s.source}: not checked"
                    f" (coverage is judged from {WINDOW_TEXT_SOURCE} records)"
                )
            continue
        checked = by_source[s.source]
        if checked.coverage is Coverage.NO_OBSERVATIONS:
            print(f"  {s.source}: no observations yet")
            continue
        if checked.coverage is Coverage.UNSETTLED:
            print(f"  {s.source}: no settled span to check yet")
            continue
        assert checked.span is not None
        start, gaps = checked.span[0], checked.gaps
        if not gaps:
            print(f"  {s.source}: no gaps since {when(start)}")
        for gap in gaps[:MAX_GAPS_SHOWN]:
            print(
                f"  warning: no {s.source} coverage from {when(gap.start)} to"
                f" {when(gap.end)} ({duration(gap.seconds)})"
            )
        if len(gaps) > MAX_GAPS_SHOWN:
            print(f"  warning: ... and {len(gaps) - MAX_GAPS_SHOWN} more {s.source} gaps")


def _print_capture_gaps(health: CaptureHealth) -> None:
    coverage = health.coverage
    if coverage is None:
        print(f"  {WINDOW_TEXT_SOURCE}: no settled span to check yet")
        return
    print(
        f"  {WINDOW_TEXT_SOURCE} from {when(coverage.start)} to {when(coverage.end)} (unobserved:"
        f" aw-afk shows you active, no record within {duration(CAPTURE_TOLERANCE.total_seconds())},"
        " not paused or asleep):"
    )
    warnings = sorted(
        [(gap, "while you were active") for gap in coverage.unobserved]
        + [(gap, "cannot be judged: no aw-afk data") for gap in coverage.unjudged]
    )
    if not warnings:
        print(f"  {WINDOW_TEXT_SOURCE}: no gaps since {when(coverage.start)}")
    for gap, why in warnings[:MAX_GAPS_SHOWN]:
        print(
            f"  warning: no {WINDOW_TEXT_SOURCE} coverage from {when(gap.start)} to {when(gap.end)}"
            f" ({duration(gap.seconds)}), {why}"
        )
    if len(warnings) > MAX_GAPS_SHOWN:
        print(f"  warning: ... and {len(warnings) - MAX_GAPS_SHOWN} more {WINDOW_TEXT_SOURCE} gaps")


def _print_agent(health: CaptureHealth, spool_path: Path, now: datetime) -> None:
    if not health.reported:
        print(f"Capture agent: has not reported yet (no {WINDOW_TEXT_SOURCE} records stored)")
        print(f"  spool         {_spool(health, spool_path, now)}")
        return
    print("Capture agent:")
    print(f"  last capture  {ago(health.last_capture, now)}")
    print(f"  alive         {_alive(health, now)}")
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


def _alive(health: CaptureHealth, now: datetime) -> str:
    last = ago(health.last_record, now)
    if health.alive == "yes":
        return f"yes (last record {last})"
    if health.alive == "no":
        return f"NO: no record since {last}, although aw-afk shows you active since then"
    if health.alive == "paused":
        return f"paused, so no records are expected (last record {last})"
    return f"cannot tell: no record since {last}, and aw-afk does not show you active since then"


def _spool(health: CaptureHealth, spool_path: Path, now: datetime) -> str:
    spool = health.spool
    if spool is None:
        return f"cannot be inspected: {health.spool_error}"
    waiting = f"{spool.waiting:,} finished file{'' if spool.waiting == 1 else 's'} waiting"
    if spool.oldest_finished_at is not None:
        age = (now - spool.oldest_finished_at).total_seconds()
        oldest = duration(age) if age >= 0 else f"{duration(-age)} ahead of now"
        waiting += f" (oldest {oldest})"
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
