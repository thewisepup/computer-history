"""Status's report: the watchdog's verdicts, thresholds and saved state, read and never written."""

from __future__ import annotations

import json
import socket
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aw_http import served_over_http
from fake_aw import FakeAW, UnreachableAW
from fake_host import FakeHost
from projectors import AW

from computer_history import cli
from computer_history.sources import (
    CAPTURE_KIND,
    SPOOL_ENV_VAR,
    SPOOL_VERSION,
    WINDOW_TEXT_SOURCE,
    IngestHealth,
    agent_config_path,
    health_path,
    write_health,
)
from computer_history.status import CaptureGaps, StatusReport, status_report
from computer_history.store import (
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


def watching(db_path: Path, since: datetime, ran_at: datetime, **saved: object) -> None:
    state = WatchdogState(ran_at=ran_at, watching_since=since, **saved)  # type: ignore[arg-type]
    write_watchdog_state(watchdog_state_path(db_path), state)


def record_line(n: int, when: datetime) -> str:
    line = {
        "version": SPOOL_VERSION,
        "id": f"00000000-0000-4000-8000-{n:012x}",
        "captured_at": when.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "kind": CAPTURE_KIND,
        "trigger": "heartbeat",
        "app_name": "Editor",
        "bundle_id": None,
        "window_title": "w",
        "text": "t",
        "text_sha256": "0" * 64,
        "full_text_bytes": 1,
        "text_cut_off": False,
        "timed_out": False,
    }
    return json.dumps(line)


def spool_record(spool: Path, when: datetime) -> None:
    spool.mkdir(parents=True, exist_ok=True)
    (spool / "open.part").write_text(record_line(1, when) + "\n", encoding="utf-8")


def report(
    db_path: Path, aw: FakeAW, *, host: FakeHost | None = None, now: datetime = NOW
) -> StatusReport:
    with open_store(db_path, Purpose.READ) as store:
        return status_report(
            store,
            aw,
            host or FakeHost(),
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


def test_after_the_laptop_was_closed_twenty_minutes_nothing_is_called_silent(db: Path) -> None:
    afk, window = f"aw-watcher-afk_{HOST}", f"aw-watcher-window_{HOST}"
    asleep = FakeAW({afk: "afkstatus", window: "currentwindow"}, t0=T0)
    asleep.add(window, 0, 40 * 60, {"app": "Editor", "title": "w"})
    asleep.add(afk, 0, 40 * 60, {"status": "not-afk"})
    spool_record(db.parent / "spool", at(40))
    last_cycle(db, at(40))
    watching(db, since=at(-60), ran_at=at(40))

    assessment = report(db, asleep).assessment

    assert [found.verdict for found in assessment.findings] == [Verdict.UNKNOWN] * 3
    assert assessment.backend.reason is Reason.RESUMED


@pytest.mark.parametrize("saved", ["none", "stopped"])
def test_without_a_running_watchdog_silence_counts_from_now(db: Path, saved: str) -> None:
    last_cycle(db, at(40))
    if saved == "stopped":
        watching(db, since=at(-60), ran_at=at(50))

    assessment = report(db, watchers()).assessment

    assert assessment.watched_since == NOW
    assert assessment.backend == Finding(Check.BACKEND, Verdict.UNKNOWN, Reason.RESUMED, at(40))


def test_the_configured_threshold_decides_when_the_backend_is_silent(db: Path) -> None:
    last_cycle(db, at(40))
    watching(db, since=at(-60), ran_at=at(59))
    agent_config_path(db).write_text(json.dumps({"watchdog": {"backend_minutes": 30}}))

    backend = report(db, watchers()).assessment.backend

    assert backend == Finding(Check.BACKEND, Verdict.OK, Reason.RECORDING, at(40))


def test_a_capture_agent_silent_while_you_were_active_is_a_problem(db: Path) -> None:
    spool_record(db.parent / "spool", at(30))
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
    assert found.aw_streams is None


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
    lines = [record_line(n, at(n)) for n in range(1, 30)]
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


def status_out(capsys: pytest.CaptureFixture[str], db_path: Path, aw_url: str) -> list[str]:
    argv = ["status", "--db-path", str(db_path), "--aw-url", aw_url]
    assert cli.main(argv) == 0
    profile, *lines = capsys.readouterr().out.splitlines()
    assert profile.startswith("Profile ")
    return lines


def ingest_line(lines: list[str]) -> str:
    [line] = [line for line in lines if line.startswith("Ingest:")]
    return line


def test_status_after_twenty_minutes_away_shows_the_afk_verdict(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, db: Path
) -> None:
    monkeypatch.delenv(SPOOL_ENV_VAR, raising=False)
    now = datetime.now(UTC)
    start = now - timedelta(minutes=60)
    last_cycle(db, at(40, start))
    watching(db, since=at(-60, start), ran_at=now - timedelta(minutes=1))
    aw = watchers(socket.gethostname(), t0=start, away_from=40)

    with served_over_http(aw) as url:
        lines = status_out(capsys, db, url)

    line = ingest_line(lines)
    assert line.startswith("Ingest:        ok, last cycle ")
    assert line.endswith("; cannot tell: silent, but aw-afk does not show you active")
    assert "NOT REPORTING" not in line


def test_status_says_not_reporting_when_the_backend_is_silent_while_you_were_active(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, db: Path
) -> None:
    monkeypatch.delenv(SPOOL_ENV_VAR, raising=False)
    now = datetime.now(UTC)
    start = now - timedelta(minutes=60)
    last_cycle(db, at(40, start))
    watching(db, since=at(-60, start), ran_at=now - timedelta(minutes=1))
    aw = watchers(socket.gethostname(), t0=start)

    with served_over_http(aw) as url:
        lines = status_out(capsys, db, url)

    assert ingest_line(lines).endswith("; NOT REPORTING for 20m (is `ingest --watch` running?)")
    assert not any(line.startswith("!! ") for line in lines)


def test_status_without_a_running_watchdog_cannot_tell_a_silent_backend(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, db: Path
) -> None:
    monkeypatch.delenv(SPOOL_ENV_VAR, raising=False)
    now = datetime.now(UTC)
    start = now - timedelta(minutes=60)
    last_cycle(db, at(40, start))
    aw = watchers(socket.gethostname(), t0=start)

    with served_over_http(aw) as url:
        lines = status_out(capsys, db, url)

    assert ingest_line(lines).endswith(
        "; cannot tell: silent, but watched only since the watchdog resumed"
    )
