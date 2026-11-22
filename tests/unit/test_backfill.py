from __future__ import annotations

import logging
import math
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cli_output import after_profile_line
from db_states import stored_progress, write_locked
from fake_aw import FakeAW
from log_records import logged
from projectors import no_signal

from computer_history import cli
from computer_history.cli import app as cli_app
from computer_history.cli import backfill as cli_backfill
from computer_history.logs import PROGRESS_RECORDS
from computer_history.sources import (
    AFK_SOURCE,
    BACKFILL_CHUNK,
    RESUME_OVERLAP_SECONDS,
    WINDOW_SOURCE,
    ActivityWatch,
    AWError,
    BackfillProgress,
    BackfillResult,
    FailureKind,
    plan_backfill,
    poll,
    run_backfill,
)
from computer_history.store import (
    ProgressUpdate,
    connect,
    get_progress,
    insert_observations,
    table_counts,
    to_utc,
    utc_iso,
)

WINDOW_BUCKET = "aw-watcher-window_test-host.local"
AFK_BUCKET = "aw-watcher-afk_test-host.local"
NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
DAYS = 20
MINUTES_PER_DAY = 1440


def history_aw(now: datetime) -> FakeAW:
    fake = FakeAW(
        {WINDOW_BUCKET: "currentwindow", AFK_BUCKET: "afkstatus"},
        t0=now - timedelta(days=DAYS),
    )
    for day in range(DAYS):
        start = day * MINUTES_PER_DAY
        fake.add(WINDOW_BUCKET, start + 60, 600, {"app": "Code", "title": f"day {day}"})
        fake.add(AFK_BUCKET, start, 3600, {"status": "not-afk"})
    fake.add(WINDOW_BUCKET, DAYS * MINUTES_PER_DAY - 5, 290, {"app": "Chrome", "title": "now"})
    fake.add(AFK_BUCKET, DAYS * MINUTES_PER_DAY - 5, 290, {"status": "not-afk"})
    return fake


def stored(conn: sqlite3.Connection, source: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT source_id, started_at, ended_at FROM observations WHERE source = ?"
        " ORDER BY started_at",
        (source,),
    ).fetchall()


def settled(conn: sqlite3.Connection, source: str = WINDOW_SOURCE) -> datetime | None:
    progress = get_progress(conn, source)
    return None if progress is None else progress.settled_until


def set_progress(conn: sqlite3.Connection, source: str, until: datetime) -> None:
    update = ProgressUpdate(source, "seeded", settled_until=until)
    insert_observations(conn, [], progress=update, project=no_signal)


def window_plan(fake: FakeAW, conn: sqlite3.Connection, **kwargs: Any):
    progress = get_progress(conn, WINDOW_SOURCE)
    return plan_backfill(ActivityWatch(fake), WINDOW_SOURCE, progress=progress, now=NOW, **kwargs)


def backfill(conn: sqlite3.Connection, fake: FakeAW, plan) -> BackfillResult:
    run = run_backfill(conn, ActivityWatch(fake), [plan], clock=lambda: NOW)
    assert run.ok, run.failure
    (result,) = run.results
    return result


def test_plan_chunks_are_fixed_width_oldest_first_from_local_midnight(conn) -> None:
    fake = history_aw(NOW)
    created = to_utc(fake.buckets[WINDOW_BUCKET]["created"])
    plan = window_plan(fake, conn)
    assert plan.start is not None

    local = plan.start.astimezone()
    assert (local.hour, local.minute, local.second, local.microsecond) == (0, 0, 0, 0)
    assert timedelta(0) <= created - plan.start < timedelta(days=1)
    assert plan.end == NOW and plan.settled_until is None
    assert len(plan.chunks) == math.ceil((NOW - plan.start) / BACKFILL_CHUNK) >= 3
    assert plan.chunks[0].start == plan.start and plan.chunks[-1].end == NOW
    for before, after in zip(plan.chunks, plan.chunks[1:], strict=False):
        assert before.end == after.start
        assert before.end - before.start == BACKFILL_CHUNK
    assert plan.chunks[-1].end - plan.chunks[-1].start <= BACKFILL_CHUNK
    assert plan.covers_history and plan.earlier == ()


def test_plan_ends_where_progress_is_settled_and_overrides_only_narrow_it(conn) -> None:
    fake = history_aw(NOW)
    until = NOW - timedelta(days=5)
    set_progress(conn, WINDOW_SOURCE, until)
    assert window_plan(fake, conn).end == until
    assert window_plan(fake, conn, end=NOW).end == until
    early = NOW - timedelta(days=12)
    start = NOW - timedelta(days=15)
    plan = window_plan(fake, conn, start=start, end=early)
    assert (plan.start, plan.end) == (start, early)
    assert plan.chunks == ((start, early),)
    nothing = window_plan(fake, conn, start=until + timedelta(hours=1))
    assert nothing.chunks == ()


def test_plan_without_created_times_has_no_start(conn) -> None:
    fake = history_aw(NOW)
    del fake.buckets[WINDOW_BUCKET]["created"]
    plan = window_plan(fake, conn)
    assert plan.start is None and plan.chunks == () and not plan.covers_history
    assert window_plan(fake, conn, start=NOW - timedelta(days=1)).chunks


def test_plan_probe_ignores_an_event_at_the_start_but_finds_one_before(conn) -> None:
    fake = FakeAW({WINDOW_BUCKET: "currentwindow"}, t0=NOW - timedelta(days=3))
    start = NOW - timedelta(days=2)
    fake.add(WINDOW_BUCKET, MINUTES_PER_DAY, 60, {"app": "A"})
    assert window_plan(fake, conn, start=start).earlier == ()
    early = fake.add(WINDOW_BUCKET, MINUTES_PER_DAY - 60, 60, {"app": "B"})
    plan = window_plan(fake, conn, start=start)
    assert plan.earlier == ((WINDOW_BUCKET, to_utc(early["timestamp"])),)
    assert not plan.covers_history


def test_backfill_ingests_all_history_across_chunks(conn) -> None:
    fake = history_aw(NOW)
    plan = window_plan(fake, conn)
    seen: list[tuple[int, int]] = []
    run = run_backfill(
        conn,
        ActivityWatch(fake),
        [plan],
        clock=lambda: NOW,
        on_chunk=lambda done: seen.append((done.index, done.inserted)),
    )
    (result,) = run.results
    assert [i for i, _ in seen] == list(range(len(plan.chunks)))
    assert sum(n for _, n in seen) == result.inserted == DAYS
    assert result.chunks_done == len(plan.chunks)
    assert result.held_back == 1
    assert len(stored(conn, WINDOW_SOURCE)) == DAYS


def test_event_straddling_a_chunk_edge_is_stored_once_and_whole(conn) -> None:
    fake = history_aw(NOW)
    plan = window_plan(fake, conn)
    edge = plan.chunks[0].end
    offset = (edge - fake.t0) / timedelta(minutes=1)
    straddler = fake.add(WINDOW_BUCKET, offset - 60, 3 * 3600, {"app": "Long"})
    on_edge = fake.add(WINDOW_BUCKET, offset, 30, {"app": "Edge"})
    first = backfill(conn, fake, plan)
    assert first.inserted == DAYS + 2

    rows = {row["source_id"]: row for row in stored(conn, WINDOW_SOURCE)}
    long_row = rows[f"{WINDOW_BUCKET}/{straddler['id']}"]
    assert to_utc(long_row["ended_at"]) - to_utc(long_row["started_at"]) == timedelta(hours=3)
    assert to_utc(rows[f"{WINDOW_BUCKET}/{on_edge['id']}"]["started_at"]) == edge

    again = backfill(conn, fake, window_plan(fake, conn, start=plan.start))
    assert (again.inserted, again.skipped) == (0, DAYS + 2)
    assert len(stored(conn, WINDOW_SOURCE)) == DAYS + 2


class RecordingAW(FakeAW):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.queries: list[dict[str, Any]] = []

    def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        self.queries.append(kwargs)
        return super().get_events(bucket_id, **kwargs)


def test_progress_set_to_final_frontier_so_ingest_does_not_rescan_history(conn) -> None:
    fake = RecordingAW({WINDOW_BUCKET: "currentwindow"}, t0=NOW - timedelta(days=DAYS))
    fake.events = {WINDOW_BUCKET: history_aw(NOW).events[WINDOW_BUCKET]}
    held_start = NOW - timedelta(minutes=5)
    plan = window_plan(fake, conn)
    result = backfill(conn, fake, plan)

    assert result.incomplete == [(plan.chunks[-1], held_start)]
    assert result.complete_until == held_start
    assert result.progress is BackfillProgress.SET
    assert settled(conn) == held_start

    fake.queries.clear()
    later = poll(conn, [ActivityWatch(fake)], now=NOW + timedelta(minutes=10)).outcomes[
        WINDOW_SOURCE
    ]
    assert later.inserted == 1
    range_queries = [q for q in fake.queries if q.get("limit") == -1]
    overlap = timedelta(seconds=RESUME_OVERLAP_SECONDS)
    assert [to_utc(q["start"]) for q in range_queries] == [
        held_start - overlap - timedelta(seconds=1)
    ]


def test_existing_progress_bounds_the_range_and_is_not_moved(conn) -> None:
    fake = history_aw(NOW)
    until = NOW - timedelta(days=10, hours=12)
    set_progress(conn, WINDOW_SOURCE, until)
    before = get_progress(conn, WINDOW_SOURCE)
    result = backfill(conn, fake, window_plan(fake, conn))
    assert result.progress is BackfillProgress.KEPT and result.incomplete == []
    assert get_progress(conn, WINDOW_SOURCE) == before
    starts = [to_utc(row["started_at"]) for row in stored(conn, WINDOW_SOURCE)]
    assert len(starts) == 10 and max(starts) < until


def test_history_before_the_floor_is_reported_and_leaves_progress_unset(conn) -> None:
    fake = history_aw(NOW)
    imported = fake.add(WINDOW_BUCKET, -3 * MINUTES_PER_DAY, 60, {"app": "Imported"})
    plan = window_plan(fake, conn)
    assert plan.earlier == ((WINDOW_BUCKET, to_utc(imported["timestamp"])),)
    result = backfill(conn, fake, plan)
    assert result.inserted == DAYS and result.progress is BackfillProgress.NOT_COVERED
    assert get_progress(conn, WINDOW_SOURCE) is None

    wider = window_plan(fake, conn, start=NOW - timedelta(days=DAYS + 5))
    assert wider.covers_history
    result = backfill(conn, fake, wider)
    assert (result.inserted, result.progress) == (1, BackfillProgress.SET)


def test_progress_set_meanwhile_wins(conn) -> None:
    fake = history_aw(NOW)
    plan = window_plan(fake, conn)
    concurrent = NOW - timedelta(minutes=30)
    set_progress(conn, WINDOW_SOURCE, concurrent)
    result = backfill(conn, fake, plan)
    assert result.progress is BackfillProgress.SET_MEANWHILE
    assert settled(conn) == concurrent


def test_progress_is_set_in_the_last_chunks_commit(conn) -> None:
    fake = history_aw(NOW)
    plan = window_plan(fake, conn)
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    result = backfill(conn, fake, plan)
    conn.set_trace_callback(None)
    commits = [i for i, sql in enumerate(statements) if sql == "COMMIT"]
    progress_writes = [i for i, sql in enumerate(statements) if "INTO ingest_progress" in sql]
    assert len(commits) == len(plan.chunks)
    assert len(progress_writes) == 1 and commits[-2] < progress_writes[0] < commits[-1]
    assert result.progress is BackfillProgress.SET and settled(conn) == result.complete_until
    progress = stored_progress(conn, WINDOW_SOURCE)
    assert progress.advanced_at == NOW


def test_a_failed_last_chunk_sets_no_progress(conn, db_path: Path) -> None:
    fake = history_aw(NOW)
    plan = window_plan(fake, conn)
    conn.execute("PRAGMA busy_timeout = 50")
    locker = sqlite3.connect(db_path, isolation_level=None)

    def lock_before_the_last(done) -> None:
        if done.index == len(plan.chunks) - 2:
            locker.execute("BEGIN IMMEDIATE")

    try:
        run = run_backfill(
            conn, ActivityWatch(fake), [plan], clock=lambda: NOW, on_chunk=lock_before_the_last
        )
    finally:
        locker.close()
    assert run.failure is not None and run.failure.kind is FailureKind.DATABASE_BUSY
    assert run.results[0].chunks_done == len(plan.chunks) - 1
    assert get_progress(conn, WINDOW_SOURCE) is None


@pytest.fixture
def use_aw(monkeypatch: pytest.MonkeyPatch):
    def install(fake: FakeAW) -> FakeAW:
        monkeypatch.setattr(cli_backfill, "AWClient", lambda *args, **kwargs: fake)
        return fake

    return install


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def chunk_lines(out: str, source: str) -> list[str]:
    return [line for line in out.splitlines() if re.match(rf"\s+{source} chunk\s+\d+/\d+", line)]


def first_plan(fake: FakeAW, now: datetime):
    source = ActivityWatch(fake)
    return plan_backfill(source, source.streams()[0], progress=None, now=now)


def expected_chunks(fake: FakeAW, now: datetime) -> int:
    return len(first_plan(fake, now).chunks)


def test_cli_backfill_creates_store_prints_progress_and_totals(
    capsys, use_aw, db_path: Path
) -> None:
    now = datetime.now(UTC)
    fake = use_aw(history_aw(now))
    assert not db_path.exists()
    code, out, _ = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 0, out
    total = expected_chunks(fake, now)
    for source in (AFK_SOURCE, WINDOW_SOURCE):
        lines = chunk_lines(out, source)
        assert len(lines) == total >= 3
        assert all(f"/{total}  [" in line for line in lines)
        assert re.search(rf"{source} done in .*: inserted {DAYS}, skipped 0, held back 1", out)
        assert re.search(rf"{source}\s+chunks\s+{total}\s+inserted\s+{DAYS}\s+skipped\s+0", out)
    assert "Backfill totals:" in out
    assert out.count("progress set: settled until") == 2
    conn = connect(db_path)
    try:
        assert table_counts(conn)["observations"] == 2 * DAYS
        assert table_counts(conn)["ingest_progress"] == 2
    finally:
        conn.close()


def test_cli_backfill_reports_the_held_back_final_chunk(capsys, use_aw, db_path: Path) -> None:
    use_aw(history_aw(datetime.now(UTC)))
    _, out, _ = run(capsys, "--db-path", str(db_path), "backfill")
    last = chunk_lines(out, WINDOW_SOURCE)[-1]
    assert re.search(r"held back\s+1 .*incomplete from ", last)
    assert all("incomplete" not in line for line in chunk_lines(out, WINDOW_SOURCE)[:-1])
    assert re.search(r"note: aw-window events from .* had not settled yet \(held back\)", out)


def test_cli_backfill_rerun_inserts_nothing(capsys, use_aw, db_path: Path) -> None:
    use_aw(history_aw(datetime.now(UTC)))
    run(capsys, "--db-path", str(db_path), "backfill")
    code, out, _ = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 0
    lines = chunk_lines(out, WINDOW_SOURCE) + chunk_lines(out, AFK_SOURCE)
    assert lines and all(re.search(r"inserted\s+0\s", line) for line in lines)
    assert re.search(rf"aw-window\s+chunks\s+\d+\s+inserted\s+0\s+skipped\s+{DAYS}", out)
    assert "progress unchanged: settled until" in out
    conn = connect(db_path)
    try:
        assert table_counts(conn)["observations"] == 2 * DAYS
    finally:
        conn.close()


def test_cli_dry_run_creates_nothing_and_lists_chunks(capsys, use_aw, db_path: Path) -> None:
    now = datetime.now(UTC)
    fake = use_aw(history_aw(now))
    code, out, _ = run(capsys, "--db-path", str(db_path), "backfill", "--dry-run")
    assert code == 0
    assert not db_path.exists()
    total = expected_chunks(fake, now)
    assert len(re.findall(rf"^\s+chunk\s+\d+/{total}  \[", out, re.MULTILINE)) == 2 * total
    assert "up to now (no ingest progress yet)" in out
    assert "dry run: nothing written" in out


def test_cli_dry_run_on_existing_store_writes_nothing_and_uses_the_progress(
    capsys, use_aw, db_path: Path
) -> None:
    use_aw(history_aw(datetime.now(UTC)))
    conn = connect(db_path)
    set_progress(conn, WINDOW_SOURCE, datetime.now(UTC) - timedelta(days=3))
    before = table_counts(conn)
    conn.close()
    mtime = db_path.stat().st_mtime_ns

    code, out, _ = run(capsys, "--db-path", str(db_path), "backfill", "--dry-run")
    assert code == 0
    assert "aw-window (1 bucket):" in out and "up to its settled-until time" in out
    assert db_path.stat().st_mtime_ns == mtime
    conn = connect(db_path)
    try:
        assert table_counts(conn) == before
    finally:
        conn.close()


def test_cli_reports_progress_without_a_settled_time_as_existing(
    capsys, use_aw, db_path: Path
) -> None:
    use_aw(history_aw(datetime.now(UTC)))
    conn = connect(db_path)
    insert_observations(
        conn, [], progress=ProgressUpdate(WINDOW_SOURCE, "spool.jsonl:7"), project=no_signal
    )
    conn.close()
    code, out, _ = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 0
    assert "aw-window (1 bucket):" in out
    assert "up to now (its ingest progress has no settled-until time)" in out
    assert "progress unchanged: it has no settled-until time" in out
    assert "another ingest set it meanwhile" not in out
    conn = connect(db_path)
    try:
        progress = stored_progress(conn, WINDOW_SOURCE)
        assert progress.position == "spool.jsonl:7"
    finally:
        conn.close()


def test_cli_start_end_overrides(capsys, use_aw, db_path: Path) -> None:
    now = datetime.now(UTC)
    use_aw(history_aw(now))
    start = (now - timedelta(days=3)).isoformat()
    end = (now - timedelta(days=1)).isoformat()
    code, out, _ = run(
        capsys, "--db-path", str(db_path), "backfill", "--start", start, "--end", end
    )
    assert code == 0
    assert len(chunk_lines(out, WINDOW_SOURCE)) == 1
    assert re.search(r"aw-window\s+chunks\s+1\s+inserted\s+2\s", out)
    assert "progress not set" in out
    conn = connect(db_path)
    try:
        assert get_progress(conn, WINDOW_SOURCE) is None
    finally:
        conn.close()


def test_cli_rejects_bad_ranges(capsys, use_aw, db_path: Path) -> None:
    use_aw(history_aw(datetime.now(UTC)))
    with pytest.raises(SystemExit) as exc:
        cli.main(["--db-path", str(db_path), "backfill", "--start", "last tuesday"])
    assert exc.value.code == 2
    assert "not an ISO date" in capsys.readouterr().err
    code, _, err = run(
        capsys,
        "--db-path",
        str(db_path),
        "backfill",
        "--start",
        "2026-11-10",
        "--end",
        "2026-11-01",
    )
    assert code == 2 and "--start must be before --end" in err
    assert not db_path.exists()


def test_when_arg_reads_naive_values_as_local_time() -> None:
    parsed = cli_app.when_arg("2026-11-01")
    assert parsed.tzinfo is UTC
    assert parsed == datetime(2026, 11, 1).astimezone().astimezone(UTC)
    assert cli_app.when_arg("2026-11-01T09:00+00:00") == datetime(2026, 11, 1, 9, tzinfo=UTC)


class DownAW(FakeAW):
    def get_buckets(self) -> dict[str, dict[str, Any]]:
        raise AWError("ActivityWatch unreachable at http://127.0.0.1:5600/api/0: refused")


def test_cli_backfill_with_aw_down_creates_nothing(capsys, use_aw, db_path: Path) -> None:
    use_aw(DownAW({}))
    code, _, err = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 1
    assert "ActivityWatch unreachable" in err and "Is ActivityWatch running?" in err
    assert "Committed chunks are kept" not in err
    assert "Traceback" not in err
    assert not db_path.exists()


class FailingAW(FakeAW):
    def __init__(self, *args: Any, ok: int, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.ok = ok

    def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        if kwargs.get("limit") == -1:
            if self.ok == 0:
                raise AWError("ActivityWatch HTTP 500 for /events")
            self.ok -= 1
        return super().get_events(bucket_id, **kwargs)


def test_cli_backfill_mid_run_failure_keeps_committed_chunks(capsys, use_aw, db_path: Path) -> None:
    now = datetime.now(UTC)
    healthy = history_aw(now)
    fake = FailingAW({WINDOW_BUCKET: "currentwindow"}, t0=healthy.t0, ok=2)
    fake.events = {WINDOW_BUCKET: healthy.events[WINDOW_BUCKET]}
    use_aw(fake)
    code, out, err = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 1
    assert len(chunk_lines(out, WINDOW_SOURCE)) == 2
    assert re.search(r"aw-window\s+chunks\s+2\s+inserted", out)
    assert "HTTP 500" in err and "re-run `computer-history backfill`" in err
    conn = connect(db_path)
    try:
        assert 0 < table_counts(conn)["observations"] < DAYS
        assert get_progress(conn, WINDOW_SOURCE) is None
    finally:
        conn.close()


def test_cli_backfill_on_a_locked_store_fails_cleanly(
    capsys, use_aw, db_path: Path, quick_busy_timeout: None
) -> None:
    use_aw(history_aw(datetime.now(UTC)))
    connect(db_path).close()
    with write_locked(db_path):
        code, _, err = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 1
    assert "database is locked" in err
    assert "Is another process writing to" in err
    assert "Committed chunks are kept" not in err
    assert "Traceback" not in err


@pytest.mark.parametrize("dry_run", [[], ["--dry-run"]], ids=["run", "dry-run"])
def test_cli_backfill_progress_read_failure_fails_cleanly(
    capsys, use_aw, db_path: Path, dry_run: list[str]
) -> None:
    use_aw(history_aw(datetime.now(UTC)))
    damaged = connect(db_path)
    damaged.execute("DROP TABLE ingest_progress")
    damaged.close()
    code, out, err = run(capsys, "--db-path", str(db_path), "backfill", *dry_run)
    assert code == 1
    assert after_profile_line(out) == ""
    assert f"cannot read {db_path}: no such table: ingest_progress" in err
    assert "Traceback" not in err


def test_backfill_help_lists_its_flags(capsys) -> None:
    with pytest.raises(SystemExit):
        cli.main(["backfill", "--help"])
    out = capsys.readouterr().out
    for flag in ("--start", "--end", "--dry-run", "--db-path", "--aw-url"):
        assert flag in out


def test_unreadable_event_before_the_start_fails_safe(conn, caplog) -> None:
    fake = history_aw(NOW)
    fake.events[WINDOW_BUCKET].append(
        {"id": 999, "timestamp": "not a time", "duration": 1, "data": {}}
    )
    plan = window_plan(fake, conn)
    assert plan.earlier == ((WINDOW_BUCKET, None),)
    assert not plan.covers_history
    [warned] = logged(caplog, "malformed event before the start, taken as uncovered history")
    assert warned["bucket"] == WINDOW_BUCKET
    result = backfill(conn, fake, plan)
    assert result.inserted == DAYS and result.progress is BackfillProgress.NOT_COVERED
    assert get_progress(conn, WINDOW_SOURCE) is None


def test_cli_warns_about_unreadable_earlier_history(capsys, use_aw, db_path: Path) -> None:
    fake = use_aw(history_aw(datetime.now(UTC)))
    fake.events[WINDOW_BUCKET].append({"id": 999, "timestamp": "??", "duration": 1, "data": {}})
    code, out, _ = run(capsys, "--db-path", str(db_path), "backfill", "--dry-run")
    assert code == 0
    assert "the newest has an unreadable timestamp" in out
    assert "progress will not be set" in out


class CountingAW(FakeAW):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.listings = 0

    def get_buckets(self) -> dict[str, dict[str, Any]]:
        self.listings += 1
        return super().get_buckets()


def test_cli_lists_buckets_once_per_run(capsys, use_aw, db_path: Path) -> None:
    healthy = history_aw(datetime.now(UTC))
    fake = CountingAW({WINDOW_BUCKET: "currentwindow", AFK_BUCKET: "afkstatus"}, t0=healthy.t0)
    fake.events = healthy.events
    use_aw(fake)
    assert run(capsys, "--db-path", str(db_path), "backfill")[0] == 0
    assert fake.listings == 1


class ProbeFailsAW(FakeAW):
    def get_events(self, bucket_id: str, **kwargs: Any) -> list[dict[str, Any]]:
        raise AWError("ActivityWatch HTTP 500 for /events")


def test_cli_planning_failure_creates_nothing_and_claims_no_progress(
    capsys, use_aw, db_path: Path
) -> None:
    use_aw(ProbeFailsAW({WINDOW_BUCKET: "currentwindow"}, t0=NOW - timedelta(days=3)))
    code, out, err = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 1
    assert "HTTP 500" in err
    assert "Committed chunks are kept" not in err
    assert "Backfill totals" not in out
    assert not db_path.exists()


def test_cli_hard_database_error_mid_run_reports_totals_and_resume_hint(
    capsys, use_aw, db_path: Path
) -> None:
    now = datetime.now(UTC)
    fake = use_aw(history_aw(now))
    edge = first_plan(fake, now).chunks[0].end
    conn = connect(db_path)
    conn.execute(
        "CREATE TRIGGER fail_after_the_first_chunk BEFORE INSERT ON observations"
        f" WHEN NEW.started_at >= '{utc_iso(edge)}'"
        " BEGIN SELECT RAISE(ABORT, 'injected hard failure'); END"
    )
    conn.close()
    code, out, err = run(capsys, "--db-path", str(db_path), "backfill")
    assert code == 1
    assert re.search(r"aw-afk\s+chunks\s+1\s+inserted", out)
    assert "backfill stopped: database error: injected hard failure" in err
    assert "Is another process writing to" not in err
    assert "Committed chunks are kept" in err
    assert "Traceback" not in err


def test_unhandled_command_fails_cleanly(capsys, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(cli.COMMANDS, "frobnicate", "Not built yet.")
    assert cli.main(["frobnicate"]) == 1
    assert "computer-history frobnicate: not implemented yet" in capsys.readouterr().err


def test_a_backfill_logs_its_start_progress_and_end(conn, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    plan = window_plan(history_aw(NOW), conn, chunk=timedelta(days=1))
    chunks = len(plan.chunks)

    backfill(conn, history_aw(NOW), plan)

    [started] = logged(caplog, "backfill started")
    assert (started["streams"], started["chunks"]) == ([WINDOW_SOURCE], chunks)
    assert started["start"] == plan.chunks[0].start.isoformat()
    step = math.ceil(chunks / PROGRESS_RECORDS)
    progress = logged(caplog, "backfill progress")
    assert [r["chunks_done"] for r in progress] == list(range(step, chunks, step))
    assert all(r["levelno"] == logging.INFO for r in progress)
    assert len(logged(caplog, "chunk committed")) == chunks
    [finished] = logged(caplog, "backfill finished")
    assert (finished["outcome"], finished["chunks_done"], finished["inserted"]) == (
        "ok",
        chunks,
        DAYS,
    )
    assert finished["streams"] == {
        WINDOW_SOURCE: {"chunks_done": chunks, "inserted": DAYS, "progress": "set"}
    }


def test_a_failed_backfill_logs_the_error_once_with_its_traceback_then_its_end(
    capsys, use_aw, db_path: Path, caplog
) -> None:
    healthy = history_aw(datetime.now(UTC))
    fake = FailingAW({WINDOW_BUCKET: "currentwindow"}, t0=healthy.t0, ok=2)
    fake.events = {WINDOW_BUCKET: healthy.events[WINDOW_BUCKET]}
    use_aw(fake)

    run(capsys, "--db-path", str(db_path), "backfill")

    [failed] = logged(caplog, "backfill failed")
    assert failed["levelno"] == logging.ERROR and failed["stream"] == WINDOW_SOURCE
    assert failed["exc_info"] is not None
    [finished] = logged(caplog, "backfill finished")
    assert (finished["outcome"], finished["chunks_done"]) == ("failed", 2)
    assert finished["levelno"] == logging.INFO
