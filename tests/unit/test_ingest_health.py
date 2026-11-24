from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import pytest
from cli_output import UNREACHABLE_AW, RunCli, ingest_line, status_out
from fake_host import FakeHost
from log_records import logged

from computer_history.cli import formatting as cli_formatting
from computer_history.cli import ingest as cli_ingest
from computer_history.host import ALERT_REPEAT
from computer_history.logs import LOG_FILE_NAME, configure
from computer_history.sources import (
    ALERT_AFTER_FAILURES,
    CycleReporter,
    CycleSummary,
    FailureKind,
    FailureStreak,
    IngestHealth,
    IngestOutcome,
    Recovery,
    StreakAlert,
    StreamFailure,
    failure_of,
    health_path,
    read_health,
    runner,
    write_health,
)

T0 = datetime(2026, 11, 19, 20, 7, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
NO_TABLE = "no such table: ingest_progress"
UNREACHABLE = "http://127.0.0.1:9"


def ok(at: datetime) -> CycleSummary:
    return CycleSummary(at, {"aw-afk": IngestOutcome(1, 0, 1, at)}, duration_s=0.25)


def failed(at: datetime, error: str = NO_TABLE) -> CycleSummary:
    return CycleSummary(at, {}, (StreamFailure("aw-afk", error, FailureKind.DATABASE_BUSY),))


class Recorder:
    def __init__(self) -> None:
        self.saved: list[IngestHealth] = []
        self.notified: list[StreakAlert] = []

    def streak(self, health: IngestHealth | None = None) -> FailureStreak:
        return FailureStreak(save=self.saved.append, notify=self.notified.append, health=health)


def test_a_streak_notifies_at_the_threshold_then_hourly_then_once_recovered() -> None:
    seen = Recorder()
    streak = seen.streak()
    streak.record(ok(T0 - MINUTE))
    for n in range(ALERT_AFTER_FAILURES - 1):
        streak.record(failed(T0 + n * MINUTE))
    assert seen.notified == []

    streak.record(failed(T0 + (ALERT_AFTER_FAILURES - 1) * MINUTE))
    assert seen.notified == [StreakAlert(ALERT_AFTER_FAILURES)]
    alerted = T0 + (ALERT_AFTER_FAILURES - 1) * MINUTE
    streak.record(failed(alerted + ALERT_REPEAT - MINUTE))
    assert len(seen.notified) == 1
    streak.record(failed(alerted + ALERT_REPEAT))
    assert seen.notified[-1] == StreakAlert(7)

    recovery = streak.record(ok(alerted + ALERT_REPEAT + MINUTE))

    assert recovery == Recovery(failed_cycles=7, failing_since=T0)
    assert seen.notified[-1] == StreakAlert(7, ended=True)
    assert seen.saved[-1] == IngestHealth(
        alerted + ALERT_REPEAT + MINUTE, last_success_at=alerted + ALERT_REPEAT + MINUTE
    )


def test_a_short_streak_ends_without_any_notification() -> None:
    seen = Recorder()
    streak = seen.streak()
    streak.record(failed(T0))
    streak.record(failed(T0 + MINUTE))

    assert streak.record(ok(T0 + 2 * MINUTE)) == Recovery(2, T0)
    assert seen.notified == []
    assert seen.streak().record(ok(T0)) is None


def test_every_cycle_saves_the_health_with_the_error_and_the_last_success() -> None:
    seen = Recorder()
    streak = seen.streak()
    streak.record(ok(T0))
    streak.record(failed(T0 + MINUTE))
    streak.record(failed(T0 + 2 * MINUTE, "database is locked"))

    assert seen.saved == [
        IngestHealth(T0, last_success_at=T0),
        IngestHealth(T0 + MINUTE, 1, T0 + MINUTE, T0, f"aw-afk: {NO_TABLE}"),
        IngestHealth(T0 + 2 * MINUTE, 2, T0 + MINUTE, T0, "aw-afk: database is locked"),
    ]


def test_a_restart_mid_streak_neither_notifies_again_early_nor_misses_the_recovery() -> None:
    seen = Recorder()
    first = seen.streak()
    for n in range(ALERT_AFTER_FAILURES):
        first.record(failed(T0 + n * MINUTE))
    assert seen.notified == [StreakAlert(ALERT_AFTER_FAILURES)]
    saved = seen.saved[-1]
    assert saved.alerted_at == T0 + (ALERT_AFTER_FAILURES - 1) * MINUTE

    restarted = seen.streak(saved)
    restarted.record(failed(T0 + ALERT_AFTER_FAILURES * MINUTE))
    restarted.record(ok(T0 + (ALERT_AFTER_FAILURES + 1) * MINUTE))

    assert seen.notified == [
        StreakAlert(ALERT_AFTER_FAILURES),
        StreakAlert(ALERT_AFTER_FAILURES + 1, ended=True),
    ]
    assert seen.saved[-1].alerted_at is None


def test_an_alert_names_the_streak_and_never_its_error() -> None:
    assert StreakAlert(5).message == "ingest failing for 5 cycles. Run `computer-history status`."
    assert StreakAlert(5, ended=True).message == "ingest recovered."


def test_a_watch_loops_failure_streak_notifies_through_the_host(
    run: RunCli, checkout: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cycles = [ALERT_AFTER_FAILURES]

    def next_cycle(_: float) -> None:
        cycles[0] -= 1
        if cycles[0] <= 0:
            raise KeyboardInterrupt

    monkeypatch.setattr(runner.time, "sleep", next_cycle)
    host = FakeHost()

    code, _, err = run(
        checkout, "ingest", "--watch", "--db-path", str(db_path), *UNREACHABLE_AW, host=host
    )

    assert code == 0, err
    assert host.notifications == [StreakAlert(ALERT_AFTER_FAILURES).message]


def test_a_restarted_watch_continues_the_saved_streak() -> None:
    seen = Recorder()
    saved = IngestHealth(T0 + 3 * MINUTE, 4, T0, T0 - MINUTE, f"aw-afk: {NO_TABLE}")
    streak = seen.streak(saved)

    streak.record(failed(T0 + 4 * MINUTE))

    assert seen.saved[-1].consecutive_failures == ALERT_AFTER_FAILURES
    assert seen.saved[-1].failing_since == T0
    assert seen.saved[-1].last_success_at == T0 - MINUTE
    assert len(seen.notified) == 1


def test_a_health_file_that_cannot_be_saved_is_logged_and_the_loop_goes_on(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    streak = FailureStreak(save=partial(write_health, tmp_path / "missing" / "h.json"), notify=None)

    streak.record(failed(T0))

    [warning] = logged(caplog, "ingest health not saved")
    assert "No such file or directory" in str(warning["error"])


def test_the_health_file_round_trips_and_is_replaced_whole(tmp_path: Path) -> None:
    path = health_path(tmp_path / "history.db")
    assert path == tmp_path / "ingest-health.json"
    assert read_health(path) is None
    health = IngestHealth(T0 + MINUTE, 3, T0, T0 - MINUTE, f"aw-afk: {NO_TABLE}", T0)

    write_health(path, IngestHealth(T0, last_success_at=T0))
    write_health(path, health)

    assert read_health(path) == health
    assert [p.name for p in tmp_path.iterdir()] == [path.name]


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[" * 100_000,
        "[1, 2]",
        '{"cycle_at": "2026-11-19"}',
        '{"cycle_at": "2026-11-19T20:07:00", "consecutive_failures": 0}',
        '{"cycle_at": "2026-11-19T20:07:00+00:00", "consecutive_failures": 1,'
        ' "failing_since": "2026-11-19T20:00:00"}',
        '{"cycle_at": "2026-11-19T20:07:00+00:00", "consecutive_failures": 1,'
        ' "sources_unavailable": "yes"}',
    ],
    ids=[
        "not-json",
        "nested-past-the-parser-limit",
        "not-an-object",
        "incomplete",
        "naive-cycle",
        "naive-since",
        "unavailable-not-a-bool",
    ],
)
def test_an_unreadable_health_file_raises_value_error(tmp_path: Path, text: str) -> None:
    path = tmp_path / "ingest-health.json"
    path.write_text(text)

    with pytest.raises(ValueError):
        read_health(path)


def test_the_cycle_record_counts_every_stream_and_times_the_cycle(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    CycleReporter(cli_ingest.cycle_line, streak=Recorder().streak())(ok(T0), 59.7)

    [record] = logged(caplog, "cycle ok: aw-afk +1 (0 dup, 1 held)")
    assert record["levelno"] == logging.INFO
    assert record["duration_ms"] == 250
    assert record["streams"] == {
        "aw-afk": {"inserted": 1, "skipped": 0, "held_back": 1, "rejected": 0}
    }


def failing(at: datetime, error: str = NO_TABLE) -> CycleSummary:
    try:
        raise sqlite3.OperationalError(error)
    except sqlite3.OperationalError as exc:
        return CycleSummary(at, {}, (failure_of("aw-afk", exc),))


def failure_records(
    caplog: pytest.LogCaptureFixture, error: str = NO_TABLE
) -> list[dict[str, object]]:
    return logged(caplog, f"cycle failed: ingest failed on aw-afk: database error: {error}")


def test_failed_cycles_are_errors_with_their_retry_delay_and_a_traceback_only_on_the_first(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    report = CycleReporter(cli_ingest.cycle_line, streak=Recorder().streak())

    for n, delay in enumerate([60.0, 44.6, 0.2]):
        report(failing(T0 + n * MINUTE), delay)
    report(ok(T0 + 3 * MINUTE), 60.0)

    errors = failure_records(caplog)
    assert [r["levelno"] for r in errors] == [logging.ERROR] * 3
    assert [r["streak"] for r in errors] == [1, 2, 3]
    assert [r["retry_s"] for r in errors] == [60, 45, 0]
    assert [r["exc_info"] is not None for r in errors] == [True, False, False]
    assert errors[0]["failures"] == [
        {"stream": "aw-afk", "kind": "database busy", "error": NO_TABLE}
    ]
    [recovered] = logged(caplog, "ingest recovered")
    assert (recovered["failed_cycles"], recovered["failing_since"]) == (3, T0.isoformat())


def test_each_new_cause_in_a_streak_and_a_restart_get_a_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    seen = Recorder()
    report = CycleReporter(cli_ingest.cycle_line, streak=seen.streak())
    report(failing(T0), 60.0)
    report(failing(T0 + MINUTE, "database is locked"), 60.0)
    report(failing(T0 + 2 * MINUTE), 60.0)
    restarted = CycleReporter(cli_ingest.cycle_line, streak=seen.streak(seen.saved[-1]))
    restarted(failing(T0 + 3 * MINUTE), 60.0)
    restarted(ok(T0 + 4 * MINUTE), 60.0)
    restarted(failing(T0 + 5 * MINUTE), 60.0)

    traced = [(r["streak"], r["exc_info"] is not None) for r in failure_records(caplog)]
    assert traced == [(1, True), (3, False), (4, True), (1, True)]
    [locked] = failure_records(caplog, "database is locked")
    assert locked["exc_info"] is not None


def test_a_one_shot_cycle_record_stays_off_stderr_but_reaches_the_log_file(
    log_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    configure("ingest", level=None, long_running=False, log_dir=log_dir)

    CycleReporter(cli_ingest.cycle_line, shown=True)(failing(T0))

    assert capsys.readouterr().err == ""
    [written] = [json.loads(line) for line in (log_dir / LOG_FILE_NAME).read_text().splitlines()]
    assert written["level"] == "error" and "shown" not in written


def test_status_reports_a_failing_ingest_first(
    db_path: Path, run: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_health(
        health_path(db_path),
        IngestHealth(T0 + 1070 * MINUTE, 1071, T0, T0 - MINUTE, f"aw-afk: {NO_TABLE}"),
    )

    monkeypatch.setattr(cli_formatting, "utc_now", lambda: T0 + 1071 * MINUTE)
    lines = status_out(run, "--db-path", str(db_path), "--aw-url", UNREACHABLE).splitlines()

    assert lines[0].startswith("!! ingest is FAILING since ")
    assert lines[0].endswith(f"(1,071 cycles): aw-afk: {NO_TABLE}")
    ingest = ingest_line(lines)
    assert "FAILING since" in ingest and "last cycle" in ingest and "NOT REPORTING" not in ingest
    assert any(line.startswith("  last success  ") for line in lines)


def test_status_without_a_watcher_says_so(
    db_path: Path, run: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli_formatting, "utc_now", lambda: T0)
    lines = status_out(run, "--db-path", str(db_path), "--aw-url", UNREACHABLE).splitlines()

    assert "Ingest:        no `ingest --watch` has reported yet" in lines
