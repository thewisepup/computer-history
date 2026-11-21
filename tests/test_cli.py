from __future__ import annotations

import logging
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cli_output import after_profile_line
from db_states import SUPPORTED, newer_db, outdated_db, user_version, write_locked
from fake_aw import FakeAW
from projectors import no_signal

import computer_history
from computer_history import cli
from computer_history.cli import backfill as cli_backfill
from computer_history.cli import formatting
from computer_history.cli import ingest as cli_ingest
from computer_history.cli import status as cli_status
from computer_history.sources import (
    AFK_SOURCE,
    POLL_INTERVAL_SECONDS,
    WINDOW_SOURCE,
    ActivityWatch,
    AWError,
    FailureKind,
    StreamFailure,
    poll,
    watch,
)
from computer_history.store import (
    DB_ENV_VAR,
    Observation,
    ProgressUpdate,
    connect,
    insert_observations,
    table_counts,
)

WINDOW_BUCKET = "aw-watcher-window_test-host.local"
AFK_BUCKET = "aw-watcher-afk_test-host.local"
UNREACHABLE = "ActivityWatch unreachable at http://127.0.0.1:5600/api/0: [Errno 61] refused"


def seeded_aw(now: datetime) -> FakeAW:
    fake = FakeAW(
        {WINDOW_BUCKET: "currentwindow", AFK_BUCKET: "afkstatus"},
        t0=now - timedelta(minutes=60),
    )
    fake.add(WINDOW_BUCKET, 0, 600, {"app": "Code", "title": "cli.py"})
    fake.add(WINDOW_BUCKET, 40, 1170, {"app": "Chrome", "title": "Docs"})
    fake.add(AFK_BUCKET, 0, 1800, {"status": "not-afk"})
    fake.add(AFK_BUCKET, 30, 1770, {"status": "afk"})
    return fake


class DownAW(FakeAW):
    def __init__(self) -> None:
        super().__init__({})

    def get_buckets(self) -> dict[str, dict[str, Any]]:
        raise AWError(UNREACHABLE)


@pytest.fixture
def use_aw(monkeypatch: pytest.MonkeyPatch):
    def install(fake: FakeAW) -> FakeAW:
        monkeypatch.setattr(cli_ingest, "AWClient", lambda *args, **kwargs: fake)
        monkeypatch.setattr(cli_status, "AWClient", lambda *args, **kwargs: fake)
        return fake

    return install


def counts_in(db_path: Path) -> dict[str, int]:
    conn = connect(db_path)
    try:
        return table_counts(conn)
    finally:
        conn.close()


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_package_imports() -> None:
    assert computer_history.__name__ == "computer_history"


def test_help_lists_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in cli.COMMANDS:
        assert command in out
    assert "--db-path" in out


def test_every_command_has_a_handler() -> None:
    assert set(cli.HANDLERS) == set(cli.COMMANDS)


def test_ingest_writes_rows_and_prints_counts(capsys, use_aw, db_path: Path) -> None:
    use_aw(seeded_aw(datetime.now(UTC)))
    code, out, _ = run(capsys, "--db-path", str(db_path), "ingest")
    assert code == 0
    assert str(db_path) in out
    assert re.search(r"aw-window\s+inserted\s+1\s+skipped\s+0\s+held back\s+1", out)
    assert re.search(r"aw-afk\s+inserted\s+1\s+skipped\s+0\s+held back\s+1", out)
    counts = counts_in(db_path)
    assert counts["observations"] == 2
    assert counts["signals"] == 1
    assert counts["ingest_progress"] == 2


def test_ingest_honors_db_env_var_and_flag_after_subcommand(
    capsys, use_aw, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    use_aw(seeded_aw(datetime.now(UTC)))
    env_db, flag_db = tmp_path / "env.db", tmp_path / "flag.db"
    monkeypatch.setenv(DB_ENV_VAR, str(env_db))
    assert run(capsys, "ingest")[0] == 0
    assert env_db.exists()
    assert run(capsys, "ingest", "--db-path", str(flag_db))[0] == 0
    assert flag_db.exists()


def test_ingest_with_no_sources(capsys, use_aw, db_path: Path) -> None:
    use_aw(FakeAW({"aw-watcher-input_x": "os.hid.input"}))
    code, out, _ = run(capsys, "--db-path", str(db_path), "ingest")
    assert code == 0
    assert "no ActivityWatch sources found" in out


def test_ingest_with_aw_down_fails_cleanly(capsys, use_aw, db_path: Path) -> None:
    use_aw(DownAW())
    code, out, err = run(capsys, "--db-path", str(db_path), "ingest")
    assert code != 0
    assert UNREACHABLE in err
    assert "Is ActivityWatch running?" in err
    assert "Traceback" not in err + out


def poll_aw(conn: sqlite3.Connection, fake: FakeAW, *, now: datetime | None = None):
    return poll(conn, [ActivityWatch(fake)], now=now)


def test_poll_returns_outcomes(conn: sqlite3.Connection) -> None:
    now = datetime.now(UTC)
    summary = poll_aw(conn, seeded_aw(now), now=now)
    assert summary.ok
    assert summary.at == now
    assert set(summary.outcomes) == {AFK_SOURCE, WINDOW_SOURCE}
    assert summary.outcomes[WINDOW_SOURCE].inserted == 1
    assert "aw-window +1 (0 dup, 1 held)" in cli_ingest.cycle_line(summary)


def test_poll_reports_aw_errors(conn: sqlite3.Connection) -> None:
    summary = poll_aw(conn, DownAW())
    assert not summary.ok
    assert summary.outcomes == {}
    assert summary.failures == (StreamFailure(None, UNREACHABLE, FailureKind.SOURCE),)
    assert cli_ingest.cycle_line(summary) == f"ingest failed: {UNREACHABLE}"


def test_poll_reports_aw_errors_mid_pull(conn: sqlite3.Connection) -> None:
    class BrokenEvents(FakeAW):
        def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
            raise AWError("ActivityWatch HTTP 500 for /events")

    summary = poll_aw(conn, BrokenEvents({WINDOW_BUCKET: "currentwindow"}))
    assert [f.error for f in summary.failures] == ["ActivityWatch HTTP 500 for /events"]
    assert table_counts(conn)["observations"] == 0


def test_watch_survives_aw_outage_and_logs_each_cycle(
    conn: sqlite3.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    healthy = seeded_aw(datetime.now(UTC))

    class FlakyAW(FakeAW):
        calls = 0

        def get_buckets(self) -> dict[str, dict[str, Any]]:
            FlakyAW.calls += 1
            if FlakyAW.calls == 1:
                raise AWError(UNREACHABLE)
            return healthy.get_buckets()

    flaky = FlakyAW({})
    flaky.buckets, flaky.events = healthy.buckets, healthy.events
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        watch(
            conn,
            [ActivityWatch(flaky)],
            report=cli_ingest.log_cycle,
            interval=POLL_INTERVAL_SECONDS,
            sleep=fake_sleep,
        )

    assert len(sleeps) == 2
    assert all(0 <= s <= POLL_INTERVAL_SECONDS for s in sleeps)
    failed, succeeded = [r for r in caplog.records if r.name == cli_ingest.__name__]
    assert failed.levelno == logging.WARNING
    assert UNREACHABLE in failed.getMessage()
    assert "retrying in 60s" in failed.getMessage()
    assert succeeded.levelno == logging.INFO
    assert "aw-window +1" in succeeded.getMessage()
    assert table_counts(conn)["observations"] == 2


class HalfBrokenAW(FakeAW):
    def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        if bucket_id == WINDOW_BUCKET:
            raise AWError("ActivityWatch HTTP 500 for /events")
        return super().get_events(bucket_id, **kwargs)


def half_broken_aw(now: datetime) -> HalfBrokenAW:
    seeded = seeded_aw(now)
    fake = HalfBrokenAW({})
    fake.buckets, fake.events = seeded.buckets, seeded.events
    return fake


def test_poll_keeps_outcomes_committed_before_a_failure(conn: sqlite3.Connection) -> None:
    summary = poll_aw(conn, half_broken_aw(datetime.now(UTC)))
    assert not summary.ok
    assert list(summary.outcomes) == [AFK_SOURCE]
    assert [f.stream for f in summary.failures] == [WINDOW_SOURCE]
    assert cli_ingest.cycle_line(summary) == (
        "aw-afk +1 (0 dup, 1 held); "
        "then ingest failed on aw-window: ActivityWatch HTTP 500 for /events"
    )
    assert table_counts(conn)["observations"] == 1


def test_ingest_prints_partial_progress_then_fails(capsys, use_aw, db_path: Path) -> None:
    use_aw(half_broken_aw(datetime.now(UTC)))
    code, out, err = run(capsys, "--db-path", str(db_path), "ingest")
    assert code == 1
    assert re.search(r"aw-afk\s+inserted\s+1", out)
    assert "aw-window" not in out
    assert "error on aw-window: ActivityWatch HTTP 500 for /events" in err
    assert counts_in(db_path)["observations"] == 1


def test_poll_survives_a_locked_database(db_path: Path) -> None:
    conn, locker = connect(db_path), connect(db_path)
    try:
        conn.execute("PRAGMA busy_timeout = 50")
        locker.execute("BEGIN IMMEDIATE")
        aw = seeded_aw(datetime.now(UTC))
        summary = poll_aw(conn, aw)
        assert summary.failures == (
            StreamFailure(AFK_SOURCE, "database is locked", FailureKind.DATABASE_BUSY),
        )
        assert cli_ingest.cycle_line(summary) == (
            "ingest failed on aw-afk: database error: database is locked"
        )
        locker.execute("ROLLBACK")
        assert poll_aw(conn, aw).ok
        assert table_counts(conn)["observations"] == 2
    finally:
        conn.close()
        locker.close()


def test_watch_survives_a_locked_database_and_logs_the_real_delay(
    db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    conn, locker = connect(db_path), connect(db_path)
    conn.execute("PRAGMA busy_timeout = 50")
    locker.execute("BEGIN IMMEDIATE")
    start = datetime.now(UTC)
    ticks = iter([0.0, 15.0, 100.0, 102.0])
    sleeps: list[float] = []

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if locker.in_transaction:
            locker.execute("ROLLBACK")
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    try:
        with pytest.raises(KeyboardInterrupt):
            watch(
                conn,
                [ActivityWatch(seeded_aw(start))],
                report=cli_ingest.log_cycle,
                interval=POLL_INTERVAL_SECONDS,
                clock=lambda: start,
                monotonic=lambda: next(ticks),
                sleep=fake_sleep,
            )
    finally:
        conn.close()
        locker.close()

    assert sleeps == [45.0, 58.0]
    failed, succeeded = [r for r in caplog.records if r.name == cli_ingest.__name__]
    assert failed.levelno == logging.WARNING
    assert failed.getMessage() == (
        "ingest failed on aw-afk: database error: database is locked; retrying in 45s"
    )
    assert "aw-afk +1" in succeeded.getMessage()


def test_ingest_watch_exits_zero_on_ctrl_c(
    capsys, use_aw, db_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    seeded = seeded_aw(datetime.now(UTC))

    class InterruptedAW(FakeAW):
        def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
            if bucket_id == WINDOW_BUCKET:
                raise KeyboardInterrupt
            return super().get_events(bucket_id, **kwargs)

    fake = InterruptedAW({})
    fake.buckets, fake.events = seeded.buckets, seeded.events
    use_aw(fake)
    code, _, err = run(capsys, "--db-path", str(db_path), "ingest", "--watch")
    assert code == 0
    assert "Traceback" not in err
    messages = [r.getMessage() for r in caplog.records if r.name == cli_ingest.__name__]
    assert any("every 60s" in m for m in messages)
    assert messages[-1] == "stopped"
    assert counts_in(db_path)["observations"] == 1


def test_status_reports_sources_lag_gaps_and_counts(capsys, use_aw, db_path: Path) -> None:
    use_aw(seeded_aw(datetime.now(UTC)))
    assert run(capsys, "--db-path", str(db_path), "ingest")[0] == 0

    code, out, _ = run(capsys, "--db-path", str(db_path), "status")
    assert code == 0
    assert "ActivityWatch: yes (http://127.0.0.1:5600/api/0; sources: aw-afk, aw-window)" in out
    assert re.search(rf"Database:\s+{re.escape(str(db_path))} \(\d+(\.\d)? [KM]?B", out)
    assert f"schema v{SUPPORTED}" in out
    assert re.search(r"aw-window\s+1 observations .* settled until .* \(20m( \d+s)? behind", out)
    assert re.search(r"aw-afk\s+1 observations .* settled until .* \(30m( \d+s)? behind", out)
    gap = re.findall(r"warning: no aw-window coverage from .+ to .+ \((.+)\)", out)
    assert gap == ["30m"]
    assert "aw-afk: no gaps since" in out
    assert "an ActivityWatch source is settled only up to" in out
    assert "unobserved" in out
    assert "idle" not in out.lower()
    assert re.search(r"observations\s+2\n", out)
    assert re.search(r"signals\s+1\n", out)


def test_status_gap_window_ends_at_settled_time_not_now(capsys, use_aw, db_path: Path) -> None:
    now = datetime.now(UTC)
    fake = FakeAW({WINDOW_BUCKET: "currentwindow"}, t0=now - timedelta(minutes=60))
    fake.add(WINDOW_BUCKET, 50, 590, {"app": "Code"})
    fake.add(WINDOW_BUCKET, 59.9, 1, {"app": "Code"})
    use_aw(fake)
    run(capsys, "--db-path", str(db_path), "ingest")
    _, out, _ = run(capsys, "--db-path", str(db_path), "status")
    assert "warning" not in out
    assert "aw-window: no gaps since" in out


def test_status_lists_many_gaps_compactly(capsys, use_aw, db_path: Path) -> None:
    now = datetime.now(UTC)
    fake = FakeAW({WINDOW_BUCKET: "currentwindow"}, t0=now - timedelta(hours=20))
    for hour in range(15):
        fake.add(WINDOW_BUCKET, hour * 60, 60, {"app": "Code"})
    fake.add(WINDOW_BUCKET, 15 * 60, 5 * 3600 - 30, {"app": "Code"})
    use_aw(fake)
    run(capsys, "--db-path", str(db_path), "ingest")
    _, out, _ = run(capsys, "--db-path", str(db_path), "status")
    assert len(re.findall(r"warning: no aw-window coverage from .* \(59m\)", out)) == 10
    assert "warning: ... and 5 more aw-window gaps" in out


def test_status_with_aw_down_still_reports_store(capsys, use_aw, db_path: Path) -> None:
    use_aw(seeded_aw(datetime.now(UTC)))
    run(capsys, "--db-path", str(db_path), "ingest")
    use_aw(DownAW())
    code, out, err = run(capsys, "--db-path", str(db_path), "status")
    assert code == 0
    first_line = after_profile_line(out).splitlines()[0]
    assert "ActivityWatch is UNREACHABLE at http://127.0.0.1:5600/api/0" in first_line
    assert UNREACHABLE in out
    assert "ActivityWatch: no" in out
    assert re.search(r"aw-window\s+1 observations", out)
    assert "Traceback" not in err


def test_status_on_missing_db_does_not_create_it(capsys, use_aw, tmp_path: Path) -> None:
    use_aw(seeded_aw(datetime.now(UTC)))
    missing = tmp_path / "nowhere" / "history.db"
    code, out, _ = run(capsys, "status", "--db-path", str(missing))
    assert code == 0
    assert f"Database:      {missing} (not created yet" in out
    assert not missing.parent.exists()


def test_status_on_fresh_db(capsys, use_aw, db_path: Path) -> None:
    connect(db_path).close()
    use_aw(FakeAW({}))
    code, out, _ = run(capsys, "--db-path", str(db_path), "status")
    assert code == 0
    assert "ActivityWatch: yes (http://127.0.0.1:5600/api/0; sources: none of" in out
    assert "Sources:\n  none yet" in out
    assert "nothing to check yet" in out
    assert re.search(r"observations\s+0\n", out)


def test_status_writes_nothing(capsys, use_aw, db_path: Path) -> None:
    use_aw(seeded_aw(datetime.now(UTC)))
    run(capsys, "--db-path", str(db_path), "ingest")
    before = db_path.read_bytes()
    assert run(capsys, "--db-path", str(db_path), "status")[0] == 0
    assert db_path.read_bytes() == before
    # A read-only WAL reader can leave an empty -wal file that the next writer removes.
    wal = Path(f"{db_path}-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    assert run(capsys, "--db-path", str(db_path), "ingest")[0] == 0
    assert not wal.exists()


def test_status_does_not_migrate_an_old_schema(capsys, use_aw, db_path: Path) -> None:
    sqlite3.connect(db_path).close()
    use_aw(FakeAW({}))
    code, out, _ = run(capsys, "--db-path", str(db_path), "status")
    assert code == 0
    assert "schema v0" in out
    assert "`computer-history ingest` will migrate the database" in out
    raw = sqlite3.connect(db_path)
    try:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 0
        assert raw.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] == 0
    finally:
        raw.close()


def test_status_reports_a_newer_schema(capsys, use_aw, db_path: Path) -> None:
    newer_db(db_path)
    use_aw(FakeAW({}))
    code, out, err = run(capsys, "--db-path", str(db_path), "status")
    assert code == 1
    assert f"schema v{SUPPORTED + 1})" in out
    assert "ActivityWatch: yes" in out
    assert "Sources:" not in out
    assert f"schema v{SUPPORTED + 1} is newer than this CLI understands (v{SUPPORTED})" in err


def test_status_checks_sources_without_progress_up_to_latest_observation(
    capsys, use_aw, db_path: Path
) -> None:
    now = datetime.now(UTC)
    obs = [
        Observation(
            WINDOW_SOURCE, f"w/{i}", now + timedelta(minutes=a), now + timedelta(minutes=b), "{}"
        )
        for i, (a, b) in enumerate([(-60, -50), (-20, -10)])
    ]
    conn = connect(db_path)
    insert_observations(conn, obs, project=no_signal)
    conn.close()
    use_aw(FakeAW({}))
    _, out, _ = run(capsys, "--db-path", str(db_path), "status")
    assert "24h up to each source's settled-until time (or its latest observation" in out
    assert "(never ingested)" in out
    assert re.findall(r"warning: no aw-window coverage from .+ to .+ \((.+)\)", out) == ["30m"]


def test_status_uses_settled_until_for_an_opaque_position(capsys, use_aw, db_path: Path) -> None:
    now = datetime.now(UTC)
    obs = [
        Observation(
            "transcript", f"c/{i}", now + timedelta(minutes=a), now + timedelta(minutes=b), ""
        )
        for i, (a, b) in enumerate([(-60, -50), (-20, -10)])
    ]
    opaque = ProgressUpdate(
        "transcript", "shots/2026-11-18T10:0042", settled_until=now - timedelta(minutes=8)
    )
    conn = connect(db_path)
    insert_observations(conn, obs, progress=opaque, project=no_signal)
    insert_observations(conn, [], progress=ProgressUpdate("ocr", "ocr/0042"), project=no_signal)
    conn.close()
    use_aw(FakeAW({}))
    code, out, _ = run(capsys, "--db-path", str(db_path), "status")
    assert code == 0
    assert re.search(r"transcript\s+2 observations .* until .* \(8m( \d+s)? behind now\)", out)
    assert re.search(r"ocr\s+0 observations .* until - \(progress moved \d+s ago\)", out)
    assert re.findall(r"warning: no transcript coverage from .+ to .+ \((.+)\)", out) == ["30m"]
    assert "ocr: no observations yet" in out


def test_status_honors_aw_url(capsys, monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    connect(db_path).close()
    seen: list[str] = []

    def fake_client(base_url: str, **kwargs: Any) -> FakeAW:
        seen.append(base_url)
        return FakeAW({})

    monkeypatch.setattr(cli_status, "AWClient", fake_client)
    _, out, _ = run(
        capsys, "--db-path", str(db_path), "status", "--aw-url", "http://127.0.0.1:5666/api/0"
    )
    assert seen == ["http://127.0.0.1:5666/api/0"]
    assert "(http://127.0.0.1:5666/api/0;" in out


EVERY_COMMAND = [
    ["ingest"],
    ["status"],
    ["rebuild-signals"],
    ["backfill"],
    ["backfill", "--dry-run"],
]


@pytest.fixture
def aw_everywhere(monkeypatch: pytest.MonkeyPatch) -> FakeAW:
    fake = seeded_aw(datetime.now(UTC))
    for module in (cli_ingest, cli_status, cli_backfill):
        monkeypatch.setattr(module, "AWClient", lambda *args, **kwargs: fake)
    return fake


@pytest.mark.parametrize("command", EVERY_COMMAND, ids=" ".join)
def test_every_command_refuses_a_newer_schema(
    capsys, aw_everywhere: FakeAW, db_path: Path, command: list[str]
) -> None:
    newer_db(db_path)
    code, _, err = run(capsys, "--db-path", str(db_path), *command)
    assert code == 1
    assert (
        f"cannot use {db_path}: schema v{SUPPORTED + 1} is newer than this CLI understands"
        f" (v{SUPPORTED}); upgrade computer-history"
    ) in err
    assert "Traceback" not in err
    assert user_version(db_path) == SUPPORTED + 1


@pytest.mark.parametrize("command", [["ingest"], ["rebuild-signals"], ["backfill"]], ids=" ".join)
def test_writing_commands_report_a_locked_db_at_open(
    capsys, aw_everywhere: FakeAW, db_path: Path, quick_busy_timeout: None, command: list[str]
) -> None:
    outdated_db(db_path)
    with write_locked(db_path):
        code, out, err = run(capsys, "--db-path", str(db_path), *command)
    assert code == 1
    assert after_profile_line(out) == ""
    assert f"cannot open {db_path}: database is locked" in err
    assert f"Is another process writing to {db_path}?" in err
    assert "Traceback" not in err
    assert user_version(db_path) == SUPPORTED - 1


@pytest.mark.parametrize("command", [["ingest"], ["backfill"]], ids=" ".join)
def test_writing_commands_migrate_an_outdated_db(
    capsys, aw_everywhere: FakeAW, db_path: Path, command: list[str]
) -> None:
    outdated_db(db_path)
    code, _, err = run(capsys, "--db-path", str(db_path), *command)
    assert code == 0, err
    assert user_version(db_path) == SUPPORTED


def test_rebuild_signals_migrates_an_outdated_db(capsys, db_path: Path) -> None:
    outdated_db(db_path)
    code, out, _ = run(capsys, "--db-path", str(db_path), "rebuild-signals")
    assert code == 0
    assert re.search(r"signals after\s+0\n", out)
    assert user_version(db_path) == SUPPORTED


def test_backfill_dry_run_refuses_an_outdated_db(
    capsys, aw_everywhere: FakeAW, db_path: Path
) -> None:
    outdated_db(db_path)
    code, out, err = run(capsys, "--db-path", str(db_path), "backfill", "--dry-run")
    assert code == 1
    assert after_profile_line(out) == ""
    assert f"cannot read {db_path}: this CLI uses schema v{SUPPORTED}" in err
    assert "`computer-history ingest` will migrate the database" in err
    assert user_version(db_path) == SUPPORTED - 1


@pytest.mark.parametrize("command", EVERY_COMMAND, ids=" ".join)
def test_every_command_reports_a_file_that_is_not_a_database(
    capsys, aw_everywhere: FakeAW, db_path: Path, command: list[str]
) -> None:
    db_path.write_bytes(b"not a database" * 100)
    code, _, err = run(capsys, "--db-path", str(db_path), *command)
    assert code == 1
    assert f"cannot open {db_path}: file is not a database" in err
    assert "Is another process writing" not in err
    assert "Traceback" not in err


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0, "0s"),
        (42.4, "42s"),
        (60, "1m"),
        (192, "3m 12s"),
        (1800, "30m"),
        (3600, "1h"),
        (7500, "2h 5m"),
        (86400, "1d"),
        (86400 + 3 * 3600 + 59, "1d 3h"),
        (86400 + 1800, "1d 30m"),
        (86400 + 5, "1d 5s"),
        (3600 + 5, "1h 5s"),
        (7200 + 60, "2h 1m"),
        (59.6, "1m"),
        (-5, "0s"),
    ],
)
def test_duration(seconds: float, text: str) -> None:
    assert formatting.duration(seconds) == text


def test_lag() -> None:
    assert formatting.lag(timedelta(seconds=42)) == "42s behind now"
    assert formatting.lag(timedelta(seconds=-90)) == "1m 30s ahead of now"


@pytest.mark.parametrize(
    ("n", "text"), [(0, "0 B"), (1023, "1023 B"), (1536, "1.5 KB"), (5 * 1024**2, "5.0 MB")]
)
def test_bytes(n: int, text: str) -> None:
    assert formatting.human_size(n) == text
