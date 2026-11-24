"""Status's report: the watchdog's verdicts, thresholds and saved state, read and never written."""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aw_http import served_over_http
from cli_output import RunCli, ingest_line, live_check, status_out
from fake_aw import FakeAW, UnreachableAW
from fake_host import FakeHost, write_record
from projectors import AW
from spool_records import spool_line

from computer_history.sources import IngestHealth, health_path, write_health
from computer_history.sources.activitywatch import AWError
from computer_history.sources.capture_spool import (
    CAPTURE_KIND,
    SPOOL_ENV_VAR,
    WINDOW_TEXT_SOURCE,
    agent_config_path,
)
from computer_history.stable import stable_layout
from computer_history.status import CaptureGaps, StatusReport, status_report
from computer_history.store import (
    STATUS_WINDOW,
    Observation,
    ProgressUpdate,
    Purpose,
    connect,
    insert_observations,
    open_store,
)
from computer_history.watchdog import Check, Finding, Reason, Verdict, watchdog_state_path
from computer_history.watchdog.state import WatchdogState, write_watchdog_state

HOST = "test-host.local"
T0 = datetime(2026, 11, 17, 10, 0, tzinfo=UTC)
NOW = T0 + timedelta(minutes=60)
BACKEND_SILENT = "backend        PROBLEM: silent while you were active, last seen"
UNREACHABLE_ERROR = "ActivityWatch unreachable at http://127.0.0.1:5600/api/0: refused"


def at(minutes: float, base: datetime = T0) -> datetime:
    return base + timedelta(minutes=minutes)


def watchers(host: str = HOST, *, t0: datetime = T0, away_from: float = 60) -> FakeAW:
    """ActivityWatch up to minute 60, with aw-afk active until away_from and away after it."""
    afk, window = f"aw-watcher-afk_{host}", f"aw-watcher-window_{host}"
    aw = FakeAW({afk: "afkstatus", window: "currentwindow"}, t0=t0)
    aw.add(window, 0, 60 * 60, {"app": "Editor", "title": "w"})
    aw.add(afk, 0, away_from * 60, {"status": "not-afk"})
    if away_from < 60:
        aw.add(afk, away_from, (60 - away_from) * 60, {"status": "afk"})
    return aw


def last_cycle(db_path: Path, when: datetime) -> None:
    write_health(health_path(db_path), IngestHealth(when, last_success_at=when))


def watching(
    db_path: Path, since: datetime, ran_at: datetime, unreachable_since: datetime | None = None
) -> None:
    state = WatchdogState(ran_at=ran_at, watching_since=since, unreachable_since=unreachable_since)
    write_watchdog_state(watchdog_state_path(db_path), state)


def report(
    db_path: Path,
    aw: FakeAW,
    *,
    host: FakeHost | None = None,
    stable_state: Path | None = None,
    now: datetime = NOW,
) -> StatusReport:
    with open_store(db_path, Purpose.READ) as store:
        return status_report(
            store,
            aw,
            host or FakeHost(),
            layout=stable_layout(),
            stable_state=stable_state or db_path.parent / "stable" / "watchdog.json",
            spool=db_path.parent / "spool",
            now=now,
            hostname=HOST,
            day_start=at(0),
        )


@pytest.fixture
def db(db_path: Path) -> Path:
    connect(db_path).close()
    return db_path


def test_away_twenty_minutes_is_afk_not_a_silent_backend(db: Path) -> None:
    last_cycle(db, at(40))
    watching(db, since=at(-60), ran_at=at(59))

    backend = report(db, watchers(away_from=40)).assessment.backend

    assert backend == Finding(Check.BACKEND, Verdict.UNKNOWN, Reason.AFK, at(40))


def test_a_backend_silent_while_you_were_active_is_a_problem(db: Path) -> None:
    last_cycle(db, at(40))
    watching(db, since=at(-60), ran_at=at(59))

    backend = report(db, watchers()).assessment.backend

    assert backend == Finding(Check.BACKEND, Verdict.PROBLEM, Reason.SILENT, at(40))


def test_just_after_the_laptop_opens_from_twenty_minutes_closed_you_were_away(db: Path) -> None:
    afk, window = f"aw-watcher-afk_{HOST}", f"aw-watcher-window_{HOST}"
    woke = FakeAW({afk: "afkstatus", window: "currentwindow"}, t0=T0)
    woke.add(window, 0, 40 * 60, {"app": "Editor", "title": "w"})
    woke.add(window, 59.9, 6, {"app": "Editor", "title": "w"})
    woke.add(afk, 0, 40 * 60, {"status": "not-afk"})
    woke.add(afk, 59.9, 6, {"status": "not-afk"})
    write_record(db.parent / "spool", CAPTURE_KIND, at(40))
    last_cycle(db, at(40))
    watching(db, since=at(-60), ran_at=at(40))

    assessment = report(db, woke).assessment

    assert assessment.backend == Finding(Check.BACKEND, Verdict.UNKNOWN, Reason.AFK, at(40))
    assert assessment.capture_agent.reason is Reason.AFK
    assert assessment.activitywatch.verdict is Verdict.OK


def test_a_running_watchdog_just_resumed_cannot_tell_yet(db: Path) -> None:
    last_cycle(db, at(40))
    watching(db, since=at(58), ran_at=at(59))

    backend = report(db, watchers()).assessment.backend

    assert backend == Finding(Check.BACKEND, Verdict.UNKNOWN, Reason.RESUMED, at(40))


@pytest.mark.parametrize("saved", ["none", "stopped"])
def test_without_a_running_watchdog_the_recent_past_counts_as_watched(db: Path, saved: str) -> None:
    if saved == "stopped":
        watching(db, since=at(-60), ran_at=at(50), unreachable_since=at(-30))
    last_cycle(db, at(40))
    write_record(db.parent / "spool", CAPTURE_KIND, at(30))
    aw = watchers()
    aw.events[f"aw-watcher-window_{HOST}"][0]["duration"] = 40 * 60

    assessment = report(db, aw).assessment

    assert assessment.watched_since == NOW - STATUS_WINDOW
    assert assessment.backend == Finding(Check.BACKEND, Verdict.PROBLEM, Reason.SILENT, at(40))
    assert assessment.capture_agent == Finding(
        Check.CAPTURE_AGENT, Verdict.PROBLEM, Reason.SILENT, at(30)
    )
    assert assessment.activitywatch.verdict is Verdict.PROBLEM
    assert assessment.activitywatch.reason is Reason.STALLED


def test_without_a_running_watchdog_a_silence_while_you_were_away_cannot_tell(db: Path) -> None:
    last_cycle(db, at(40))

    backend = report(db, watchers(away_from=40)).assessment.backend

    assert backend == Finding(Check.BACKEND, Verdict.UNKNOWN, Reason.AFK, at(40))


def test_without_a_running_watchdog_an_outage_counts_from_now(db: Path) -> None:
    watching(db, since=at(-60), ran_at=at(50), unreachable_since=at(-30))

    activitywatch = report(db, UnreachableAW()).assessment.activitywatch

    assert (activitywatch.verdict, activitywatch.last_seen) == (Verdict.UNKNOWN, NOW)


def test_the_stable_watchdog_state_beside_the_database_is_read_for_both_uses(db: Path) -> None:
    watching(db, since=at(-60), ran_at=at(59))

    found = report(db, watchers(), stable_state=watchdog_state_path(db))

    assert found.assessment.watched_since == at(-60)
    assert found.watchdog.state.ran_at == at(59) and found.watchdog.error is None


def test_the_configured_threshold_decides_when_the_backend_is_silent(db: Path) -> None:
    last_cycle(db, at(40))
    watching(db, since=at(-60), ran_at=at(59))
    agent_config_path(db).write_text(json.dumps({"watchdog": {"backend_minutes": 30}}))

    backend = report(db, watchers()).assessment.backend

    assert backend == Finding(Check.BACKEND, Verdict.OK, Reason.RECORDING, at(40))


def test_a_capture_agent_silent_while_you_were_active_is_a_problem(db: Path) -> None:
    write_record(db.parent / "spool", CAPTURE_KIND, at(30))
    watching(db, since=at(-60), ran_at=at(59))

    capture = report(db, watchers()).assessment.capture_agent

    assert capture == Finding(Check.CAPTURE_AGENT, Verdict.PROBLEM, Reason.SILENT, at(30))


def test_activitywatch_unreachable_since_the_saved_outage(db: Path) -> None:
    watching(db, since=at(-60), ran_at=at(59), unreachable_since=at(50))

    found = report(db, UnreachableAW())

    activitywatch = found.assessment.activitywatch
    assert activitywatch == Finding(
        Check.ACTIVITYWATCH, Verdict.PROBLEM, Reason.UNREACHABLE, at(50), UNREACHABLE_ERROR
    )
    assert found.assessment.aw_sources is None


def test_the_activitywatch_line_rests_on_one_bucket_listing(db: Path) -> None:
    aw = watchers()
    listing = aw.get_buckets
    listings: list[int] = []

    def gone_after_the_first() -> dict[str, dict[str, object]]:
        listings.append(1)
        if len(listings) > 1:
            raise AWError("ActivityWatch unreachable: refused")
        return listing()

    aw.get_buckets = gone_after_the_first
    assessment = report(db, aw).assessment

    assert assessment.aw_sources == ("aw-afk", "aw-window")
    assert assessment.activitywatch.reason is not Reason.UNREACHABLE


def test_status_writes_no_state_notifies_nothing_and_never_reopens_activitywatch(
    db: Path,
) -> None:
    host = FakeHost()
    host.running_activitywatch = False
    last_cycle(db, at(40))

    found = report(db, UnreachableAW(), host=host)

    assert found.assessment.activitywatch.reason is Reason.UNREACHABLE
    assert not watchdog_state_path(db).exists()
    assert host.notifications == []
    assert ("open_activitywatch", "") not in host.calls


def test_window_text_gaps_come_from_the_capture_agents_records(db: Path) -> None:
    conn = connect(db)
    lines = [spool_line(n, at(n)) for n in range(1, 30)]
    observations = [
        Observation(WINDOW_TEXT_SOURCE, str(n), at(n), at(n), line)
        for n, line in enumerate(lines, start=1)
    ]
    progress = ProgressUpdate(WINDOW_TEXT_SOURCE, at(29).isoformat(), settled_until=at(29))
    insert_observations(conn, observations, project=AW, progress=progress)
    conn.close()

    details = report(db, watchers()).store

    assert details is not None and details.capture.reported
    [gaps] = details.gaps
    assert isinstance(gaps, CaptureGaps) and gaps.coverage is not None


def test_status_after_twenty_minutes_away_shows_the_afk_verdict(
    run: RunCli, monkeypatch: pytest.MonkeyPatch, db: Path
) -> None:
    monkeypatch.delenv(SPOOL_ENV_VAR, raising=False)
    now = datetime.now(UTC)
    start = now - timedelta(minutes=60)
    last_cycle(db, at(40, start))
    watching(db, since=at(-60, start), ran_at=now - timedelta(minutes=1))
    aw = watchers(socket.gethostname(), t0=start, away_from=40)

    with served_over_http(aw) as url:
        lines = status_out(run, "--db-path", str(db), "--aw-url", url).splitlines()

    assert ingest_line(lines).startswith("Ingest:        ok, last cycle ")
    assert "cannot tell: silent, but aw-afk does not show you active, last seen" in live_check(
        lines, Check.BACKEND
    )


def test_status_says_not_reporting_when_the_backend_is_silent_while_you_were_active(
    run: RunCli, monkeypatch: pytest.MonkeyPatch, db: Path
) -> None:
    monkeypatch.delenv(SPOOL_ENV_VAR, raising=False)
    now = datetime.now(UTC)
    start = now - timedelta(minutes=60)
    last_cycle(db, at(40, start))
    watching(db, since=at(-60, start), ran_at=now - timedelta(minutes=1))
    aw = watchers(socket.gethostname(), t0=start)

    with served_over_http(aw) as url:
        lines = status_out(run, "--db-path", str(db), "--aw-url", url).splitlines()

    backend = live_check(lines, Check.BACKEND)
    assert BACKEND_SILENT in backend and backend.endswith(" (20m ago)")
    assert not any(line.startswith("!! ") for line in lines)
